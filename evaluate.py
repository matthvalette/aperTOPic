import asyncio
from main import classify_with_apertus

# Sample test cases representing multilingual parliamentary data
TEST_SAMPLES = [
    {
        "id": "101",
        "title": "E-Government Strategy and E-ID Implementation",
        "text": "Motion regarding digital public services and infrastructure across federal agencies.",
        "language": "de",
        "expected_topic": "Digitalisation"
    },
    {
        "id": "102",
        "title": "Financement des énergies renouvelables",
        "text": "Projet de loi concernant les subventions pour les panneaux solaires.",
        "language": "fr",
        "expected_topic": "Energy"
    }
]

def run_evaluation():
    correct = 0
    topics = ["Digitalisation", "Energy", "Economy", "Health"]

    print("--- Starting Evaluation on Labelled Sample ---")
    for sample in TEST_SAMPLES:
        res = classify_with_apertus(sample, topics)
        is_correct = res.primary_topic == sample["expected_topic"]
        if is_correct:
            correct += 1
        
        print(f"ID: {sample['id']} | Lang: {sample['language']}")
        print(f"Predicted: {res.primary_topic} | Expected: {sample['expected_topic']}")
        print(f"Match: {is_correct} | Confidence: {res.confidence_score}")
        print(f"Evidence: {res.key_passage_evidence}\n" + "-"*40)

    accuracy = (correct / len(TEST_SAMPLES)) * 100
    print(f"Overall Classification Accuracy: {accuracy:.2f}%")

if __name__ == "__main__":
    run_evaluation()