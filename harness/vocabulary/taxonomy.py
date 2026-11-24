"""Topic taxonomy and language functions for IELTS Vocabulary Knowledge Base."""

from typing import Dict, List, Set, Tuple

# 20 Shared Topics
TOPIC_TAXONOMY: Dict[str, Dict[str, str]] = {
    "education_and_learning": {
        "id": "education_and_learning",
        "name": "Education and Learning",
        "description": "Schools, higher education, academic study, learning methods, exams, students, and qualifications",
        "keywords": "education, school, university, college, student, study, academic, learn, cram, degree, scholarship, lecture, tutorial, course, syllabus, exam",
    },
    "work_and_careers": {
        "id": "work_and_careers",
        "name": "Work and Careers",
        "description": "Jobs, employment, career development, recruitment, workplace routines, and job satisfaction",
        "keywords": "work, job, career, employment, profession, occupation, employee, employer, salary, wage, hire, interview, routine, workplace, resign, retire",
    },
    "business_and_economy": {
        "id": "business_and_economy",
        "name": "Business and Economy",
        "description": "Commerce, markets, finance, management, trade, industry, enterprise, and marketing",
        "keywords": "business, economy, trade, market, commerce, company, profit, loss, investment, management, marketing, sales, consumer, finance, enterprise",
    },
    "environment_and_climate": {
        "id": "environment_and_climate",
        "name": "Environment and Climate",
        "description": "Climate change, global warming, pollution, natural resources, energy, ecology, and conservation",
        "keywords": "environment, climate, weather, pollution, global warming, conservation, ecosystem, sustainable, emissions, energy, renewable, natural resources",
    },
    "science_and_technology": {
        "id": "science_and_technology",
        "name": "Science and Technology",
        "description": "Scientific discovery, innovation, computers, artificial intelligence, research, and technical progress",
        "keywords": "science, technology, research, experiment, computer, software, digital, innovation, discovery, internet, artificial intelligence, robotics",
    },
    "health_and_medicine": {
        "id": "health_and_medicine",
        "name": "Health and Medicine",
        "description": "Healthcare, illness, diseases, medicine, mental and physical development, diet, and wellness",
        "keywords": "health, medicine, disease, illness, hospital, doctor, patient, diet, nutrition, fitness, physical, mental, treatment, cure, symptom",
    },
    "transport_and_travel": {
        "id": "transport_and_travel",
        "name": "Transport and Travel",
        "description": "Public transport, roads, traffic, aviation, railways, tourism, holidaying, and commuting",
        "keywords": "transport, travel, tourism, journey, vehicle, car, bus, train, traffic, commute, aviation, flight, accommodation, destination",
    },
    "crime_and_law": {
        "id": "crime_and_law",
        "name": "Crime and Law",
        "description": "Legal systems, crime, law enforcement, courts, punishment, policing, and justice",
        "keywords": "crime, law, legal, justice, police, criminal, court, judge, punishment, prison, sentence, offense, trial, legislation, illegal",
    },
    "government_and_politics": {
        "id": "government_and_politics",
        "name": "Government and Politics",
        "description": "State control, policy, public administration, democracy, governance, and public institutions",
        "keywords": "government, policy, state, authority, politics, democracy, public sector, minister, legislation, governance, regulation, official",
    },
    "society_and_global_issues": {
        "id": "society_and_global_issues",
        "name": "Society and Global Issues",
        "description": "Poverty, inequality, immigration, globalisation, demographic change, and human rights",
        "keywords": "society, global, community, poverty, population, immigration, human rights, inequality, culture, international, social issue, welfare",
    },
    "media_and_communication": {
        "id": "media_and_communication",
        "name": "Media and Communication",
        "description": "News, broadcasting, journalism, social media, advertising, public relations, and information bias",
        "keywords": "media, communication, news, journalism, television, radio, internet, social media, advertising, headline, press, broadcast, reporting",
    },
    "people_and_relationships": {
        "id": "people_and_relationships",
        "name": "People and Relationships",
        "description": "Family, friendship, personality, appearance, social interactions, and human life stages",
        "keywords": "people, family, relationship, friend, parent, child, relative, personality, character, appearance, behaviour, adulthood, childhood",
    },
    "food_and_lifestyle": {
        "id": "food_and_lifestyle",
        "name": "Food and Lifestyle",
        "description": "Diet, eating habits, lifestyle, leisure routines, cooking, and consumption",
        "keywords": "food, drink, meal, diet, cooking, cuisine, restaurant, lifestyle, habit, nutrition, eating, consumption",
    },
    "culture_and_arts": {
        "id": "culture_and_arts",
        "name": "Culture and Arts",
        "description": "Visual arts, literature, theatre, cinema, music, heritage, architecture, and personal taste",
        "keywords": "culture, art, music, literature, theatre, film, movie, performance, heritage, festival, creative, exhibition, artistic, entertainment",
    },
    "housing_and_urbanisation": {
        "id": "housing_and_urbanisation",
        "name": "Housing and Urbanisation",
        "description": "Cities, towns, urban planning, countryside vs urban living, accommodation, and buildings",
        "keywords": "housing, urban, city, town, urbanisation, rural, countryside, accommodation, flat, apartment, infrastructure, architecture, suburb",
    },
    "nature_and_animals": {
        "id": "nature_and_animals",
        "name": "Nature and Animals",
        "description": "Wildlife, fauna, flora, habitats, geography, oceans, and natural phenomena",
        "keywords": "nature, animal, wildlife, species, plant, habitat, fauna, flora, earth, ocean, geography, natural history, biodiversity",
    },
    "academic_language": {
        "id": "academic_language",
        "name": "Academic Language",
        "description": "Academic style, structuring essays, research terminology, citation, and formal academic discourse",
        "keywords": "academic, research, essay, assignment, lecture, report, hypothesis, theory, evidence, citation, analysis, terminology, discourse",
    },
    "feelings_and_behaviour": {
        "id": "feelings_and_behaviour",
        "name": "Feelings and Behaviour",
        "description": "Emotions, psychological reactions, attitudes, motivation, and human conduct",
        "keywords": "feeling, emotion, behaviour, attitude, reaction, psychological, mental, mood, anxious, confident, angry, happy, motivation, stress",
    },
    "sport_and_leisure": {
        "id": "sport_and_leisure",
        "name": "Sport and Leisure",
        "description": "Athletics, games, exercise, hobbies, recreation, and physical activities",
        "keywords": "sport, game, exercise, leisure, hobby, recreation, athlete, competition, football, fitness, outdoor, pastime",
    },
    "abstract_concepts": {
        "id": "abstract_concepts",
        "name": "Abstract Concepts",
        "description": "Time, space, degree, distance, change, speed, truth, existence, and classification",
        "keywords": "concept, time, change, space, distance, speed, frequency, degree, truth, abstract, perspective, principle, dimension",
    },
}

# 14 Language Functions
LANGUAGE_FUNCTIONS: Dict[str, Dict[str, str]] = {
    "cause_and_effect": {
        "id": "cause_and_effect",
        "name": "Cause and Effect",
        "description": "Expressing causation, consequence, triggers, results, and contributing factors",
    },
    "comparison_and_contrast": {
        "id": "comparison_and_contrast",
        "name": "Comparison and Contrast",
        "description": "Expressing similarities, differences, distinctions, and degrees of disparity",
    },
    "argumentation": {
        "id": "argumentation",
        "name": "Argumentation",
        "description": "Developing arguments, counterarguments, refutations, and balanced discussions",
    },
    "agreement_and_disagreement": {
        "id": "agreement_and_disagreement",
        "name": "Agreement and Disagreement",
        "description": "Expressing consensus, concessions, disputes, and conflicting viewpoints",
    },
    "describing_trends": {
        "id": "describing_trends",
        "name": "Describing Trends",
        "description": "Describing increases, decreases, fluctuations, plateaus, and rates of change",
    },
    "quantity_and_degree": {
        "id": "quantity_and_degree",
        "name": "Quantity and Degree",
        "description": "Expressing proportions, amounts, intensities, limits, and approximations",
    },
    "evaluation": {
        "id": "evaluation",
        "name": "Evaluation",
        "description": "Appraising value, significance, effectiveness, strengths, and limitations",
    },
    "register": {
        "id": "register",
        "name": "Register",
        "description": "Distinguishing formal, informal, academic, colloquial, and idiomatic styles",
    },
    "word_formation": {
        "id": "word_formation",
        "name": "Word Formation",
        "description": "Prefixes, suffixes, compounding, and derivation within word families",
    },
    "classification": {
        "id": "classification",
        "name": "Classification",
        "description": "Categorizing, grouping, dividing, and ordering items or concepts",
    },
    "problem_and_solution": {
        "id": "problem_and_solution",
        "name": "Problem and Solution",
        "description": "Framing issues, difficulties, obstacles, and remedial interventions",
    },
    "definition_and_explanation": {
        "id": "definition_and_explanation",
        "name": "Definition and Explanation",
        "description": "Clarifying concepts, defining terms, illustrating, and expanding on meanings",
    },
    "evidence_and_reasoning": {
        "id": "evidence_and_reasoning",
        "name": "Evidence and Reasoning",
        "description": "Supporting claims with empirical data, examples, deductions, and rationale",
    },
    "academic_reporting": {
        "id": "academic_reporting",
        "name": "Academic Reporting",
        "description": "Reporting findings, citing authors, summarizing research, and hedging claims",
    },
}


def classify_topics_by_keywords(text: str) -> List[str]:
    """Matches text against topic keywords, returning matching topic IDs."""
    text_lower = text.lower()
    matched = []
    for topic_id, data in TOPIC_TAXONOMY.items():
        kw_list = [kw.strip() for kw in data["keywords"].split(",")]
        # Count keyword hits
        hits = sum(1 for kw in kw_list if kw in text_lower)
        if hits > 0:
            matched.append((topic_id, hits))
    matched.sort(key=lambda x: x[1], reverse=True)
    return [t[0] for t in matched]
