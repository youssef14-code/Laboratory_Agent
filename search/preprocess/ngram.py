from typing import Set

def generate_ngrams(text: str, n: int = 2) -> Set[str]: 
    text = text.lower().strip().replace(" ", "")
    
    if not text:
        return set()
        
    padded_text = f"${text}$"
    
    if len(padded_text) < n:
        return {padded_text}

    return {
        padded_text[i:i+n] 
        for i in range(len(padded_text)-n+1)
    }

def ngram_similarity(query: str, candidate: str, n: int = 2) -> float:
    q = generate_ngrams(query, n)
    c = generate_ngrams(candidate, n)

    if not q or not c:
        return 0.0

    intersection = len(q & c)
    union = len(q | c)

    return intersection / union

