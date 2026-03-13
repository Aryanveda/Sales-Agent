import os

INPUT_FILE = "aaryanveda_knowledge.txt"
OUTPUT_DIR = "chunks"
CHUNK_SIZE = 10000


def clean_text(text: str) -> str:
    """
    Cleans crawler text.
    - removes empty lines
    - merges broken lines
    """

    lines = text.splitlines()

    cleaned = []
    buffer = ""

    for line in lines:
        line = line.strip()

        if not line:
            continue

        # merge short noisy lines (like "FAQs", "Share", "Link")
        if len(line.split()) <= 2:
            buffer += " " + line
        else:
            if buffer:
                cleaned.append(buffer.strip())
                buffer = ""
            cleaned.append(line)

    if buffer:
        cleaned.append(buffer.strip())

    return " ".join(cleaned)


def chunk_text(text: str, chunk_size: int = 800):
    """
    Split text into fixed word chunks.
    """

    words = text.split()

    chunks = []

    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        chunks.append(" ".join(chunk))

    return chunks


def save_chunks(chunks):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for i, chunk in enumerate(chunks, start=1):

        filename = os.path.join(OUTPUT_DIR, f"chunk_{i}.txt")

        with open(filename, "w", encoding="utf-8") as f:
            f.write(chunk)


def main():

    if not os.path.exists(INPUT_FILE):
        print("Input file not found:", INPUT_FILE)
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_text = f.read()

    cleaned_text = clean_text(raw_text)

    chunks = chunk_text(cleaned_text, CHUNK_SIZE)

    save_chunks(chunks)

    print(f"Total chunks created: {len(chunks)}")
    print(f"Chunks saved in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()