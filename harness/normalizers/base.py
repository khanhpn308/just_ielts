"""Base normalizer and canonical serialization utilities for IELTS Data Harness V0.2."""

from __future__ import annotations

import abc
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel

NORMALIZER_VERSION = "0.2.0-b"
SCHEMA_VERSION = "v0.2.0-normalized"


def compute_canonical_content_hash(payload: Dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash over canonical payload fields.

    Recursively excludes volatile execution fields ('normalized_at' and
    'canonical_content_sha256') so that re-runs over identical semantic data
    yield identical content digests regardless of run timestamp.
    """
    def filter_canonical(node: Any) -> Any:
        if isinstance(node, dict):
            filtered = {}
            for k in sorted(node.keys()):
                if k in {"normalized_at", "canonical_content_sha256"}:
                    continue
                filtered[k] = filter_canonical(node[k])
            return filtered
        elif isinstance(node, list):
            return [filter_canonical(x) for x in node]
        return node

    canonical_obj = filter_canonical(payload)
    serialized = json.dumps(canonical_obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def serialize_canonical_json(payload: Dict[str, Any]) -> str:
    """Serializes a dictionary into canonical byte-identical JSON string.

    Enforces 2-space indentation, lexicographical key sorting, UTF-8 compatibility,
    and a trailing newline without carriage returns.
    """
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def atomic_write_json(file_path: Path | str, data: Dict[str, Any]) -> None:
    """Atomically writes JSON payload to destination path.

    Writes to a temporary file in the destination directory, ensures disk sync,
    and atomically renames to the final target path.
    """
    target = Path(file_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_name = f".{target.name}.tmp_{os.getpid()}_{uuid4().hex[:8]}"
    temp_path = target.parent / temp_name

    content = serialize_canonical_json(data)
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def validate_output_privacy(
    target_path: Path | str,
    payload: Dict[str, Any],
    authorized_private_roots: Optional[List[Path]] = None,
) -> Path:
    """Enforces strict repository privacy policy before writing to disk.

    - Resolves target path to prevent traversal (..) and symlink escapes.
    - Rejects private_copyrighted entities targeted outside authorized private storage.
    """
    from harness.config import REPO_ROOT

    resolved = Path(target_path).resolve()
    qp = payload.get("quality_profile", {})
    permission = qp.get("publication_permission")

    if permission == "private_copyrighted":
        if authorized_private_roots:
            allowed_roots = [r.resolve() for r in authorized_private_roots]
        else:
            allowed_roots = [(REPO_ROOT / "private").resolve()]

        is_authorized = any(
            resolved == r or r in resolved.parents or (hasattr(resolved, "is_relative_to") and resolved.is_relative_to(r))
            for r in allowed_roots
        )
        if not is_authorized:
            raise PermissionError(
                f"Privacy policy violation: entity with publication_permission='{permission}' "
                f"cannot be written to unauthorized path '{resolved}'. "
                f"Authorized private roots: {[str(r) for r in allowed_roots]}"
            )

    return resolved


class BaseNormalizer(abc.ABC):
    """Abstract base class for all V0.2 normalizers."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION):
        self.normalizer_version = normalizer_version

    @abc.abstractmethod
    def normalize(self, *args: Any, **kwargs: Any) -> Any:
        """Execute normalization logic transforming raw input into canonical entities."""
        pass

    @staticmethod
    def finalize_and_hash_entity(entity: BaseModel | Dict[str, Any]) -> Dict[str, Any]:
        """Calculates canonical content hash, updates _provenance, and returns dictionary."""
        if isinstance(entity, BaseModel):
            payload = entity.model_dump(by_alias=True)
        else:
            payload = dict(entity)

        # Compute hash over payload (excluding timestamps and existing hash)
        c_hash = compute_canonical_content_hash(payload)

        # Inject canonical hash into _provenance block
        if "_provenance" in payload and isinstance(payload["_provenance"], dict):
            payload["_provenance"]["canonical_content_sha256"] = c_hash

        return payload

    @staticmethod
    def write_entity(
        target_path: Path | str,
        entity: BaseModel | Dict[str, Any],
        authorized_private_roots: Optional[List[Path]] = None,
    ) -> Path:
        """Finalizes entity hashing, validates privacy policy, and atomically writes to disk."""
        payload = BaseNormalizer.finalize_and_hash_entity(entity)
        target = validate_output_privacy(target_path, payload, authorized_private_roots)
        atomic_write_json(target, payload)
        return target
