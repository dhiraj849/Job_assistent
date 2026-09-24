import numpy as np
from fastembed import TextEmbedding

model = TextEmbedding("BAAI/bge-small-en-v1.5")

profile = (
    "Python backend developer with 5 years of experience "
    "in Django, FastAPI, PostgreSQL, AWS and Docker"
)

jobs = [
    "Senior Python Developer - build REST APIs with FastAPI and PostgreSQL",
    "Django Backend Engineer for a fintech startup",
    "Software Engineer II - design and scale backend APIs",
    "React Frontend Developer with TypeScript",
    "Java Spring Boot Microservices Engineer",
    "Data Entry Operator",
]

profile_vector = list(model.embed([profile]))[0]
job_vectors = list(model.embed(jobs))

print("Vector length:", len(profile_vector))
print("First 5 numbers:", profile_vector[:5])
print()


def cosine_similarity(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


scores = []
for job, vector in zip(jobs, job_vectors):
    scores.append((cosine_similarity(profile_vector, vector), job))

for score, job in sorted(scores, reverse=True):
    print(f"{score:.3f}  {job}")