"""
KnowledgeAgent: indexa documentos (PDF, DOCX, TXT), los convierte en vectores
con Gemini (text-embedding-004 / gemini-embedding-001) y los guarda en data/vector_db/.
Permite búsqueda semántica para que AnalystAgent complemente sus análisis con contexto
de documentos de negocio (reglas, reportes internos, etc.).
"""
import os
import json
from pathlib import Path
from typing import List, Tuple, Optional

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Modelo de embeddings: la API actual expone gemini-embedding-001; text-embedding-004
# puede estar disponible en Vertex AI; cambiar aquí si usas otro endpoint.
EMBEDDING_MODEL = "models/gemini-embedding-001"

# Extensiones soportadas para indexación
DOC_EXTENSIONS = (".pdf", ".docx", ".doc", ".txt")

# Carpeta por defecto de la base vectorial (relativa al directorio del proyecto Malcom)
DEFAULT_VECTOR_DB_PATH = "data/vector_db"

# Tamaño máximo de chunk en caracteres (Gemini tiene límite por request)
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


def _extract_text_txt(file_path: str) -> str:
    """Extrae texto de un archivo .txt."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _extract_text_pdf(file_path: str) -> str:
    """Extrae texto de un PDF usando pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extract_text_docx(file_path: str) -> str:
    """Extrae texto de un DOCX usando python-docx."""
    from docx import Document
    doc = Document(file_path)
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_text_from_file(file_path: str) -> Optional[str]:
    """
    Extrae el texto de un archivo según su extensión.
    Soporta: .pdf, .docx, .doc, .txt.
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None
    suffix = path.suffix.lower()
    try:
        if suffix == ".txt":
            return _extract_text_txt(file_path)
        if suffix == ".pdf":
            return _extract_text_pdf(file_path)
        if suffix in (".docx", ".doc"):
            return _extract_text_docx(file_path)
    except Exception as e:
        print(f"KnowledgeAgent: error extrayendo texto de {file_path}: {e}")
        return None
    return None


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Divide el texto en chunks con solapamiento para no cortar frases."""
    if not text or not text.strip():
        return []
    text = text.strip()
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            # Intentar cortar en un salto de línea o punto
            break_at = text.rfind("\n", start, end + 1)
            if break_at == -1:
                break_at = text.rfind(". ", start, end + 1)
            if break_at != -1:
                end = break_at + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if overlap < (end - start) else end
    return chunks


class KnowledgeAgent:
    """
    Indexa documentos (PDF, DOCX, TXT), genera embeddings con Gemini y guarda
    la base vectorial en data/vector_db/. Permite búsqueda semántica para
    enriquecer el análisis del AnalystAgent.
    """

    def __init__(self, vector_db_path: Optional[str] = None):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self._vector_db_path = Path(vector_db_path or DEFAULT_VECTOR_DB_PATH)
        self._vector_db_path.mkdir(parents=True, exist_ok=True)
        self._embeddings_file = self._vector_db_path / "embeddings.json"
        self._metadata_file = self._vector_db_path / "metadata.json"
        self._embeddings: List[List[float]] = []
        self._metadata: List[dict] = []  # [{"source": path, "text": chunk}, ...]
        self._load_db()

    def _load_db(self) -> None:
        """Carga la base vectorial desde disco si existe."""
        self._embeddings = []
        self._metadata = []
        if self._embeddings_file.exists():
            try:
                with open(self._embeddings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._embeddings = data.get("embeddings", [])
                with open(self._metadata_file, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
            except Exception as e:
                print(f"KnowledgeAgent: error cargando vector_db: {e}")

    def _save_db(self) -> None:
        """Persiste embeddings y metadata en data/vector_db/."""
        self._vector_db_path.mkdir(parents=True, exist_ok=True)
        with open(self._embeddings_file, "w", encoding="utf-8") as f:
            json.dump({"embeddings": self._embeddings}, f, ensure_ascii=False)
        with open(self._metadata_file, "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, ensure_ascii=False, indent=0)

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Genera embeddings para una lista de textos con Gemini."""
        if not texts:
            return []
        result = []
        # La API puede tener límite por request; procesamos en lotes pequeños
        batch_size = 20
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                response = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=batch,
                )
                # embed_content con lista devuelve BatchEmbeddingDict
                if isinstance(response, dict):
                    emb = response.get("embedding", response.get("embeddings", []))
                    if isinstance(emb, list) and emb and isinstance(emb[0], list):
                        result.extend(emb)  # batch: list of vectors
                    elif isinstance(emb, list) and emb and isinstance(emb[0], (int, float)):
                        result.append(emb)  # single vector
                    else:
                        result.append(emb if isinstance(emb, list) else [])
                else:
                    result.append(response)
            except Exception as e:
                print(f"KnowledgeAgent: error en embed_content: {e}")
                # Fallback: un embedding por texto si la API solo acepta uno
                for text in batch:
                    try:
                        r = genai.embed_content(model=EMBEDDING_MODEL, content=text)
                        emb = r.get("embedding", r) if isinstance(r, dict) else r
                        if isinstance(emb, list) and len(emb) > 0:
                            result.append(emb)
                        else:
                            result.append([])
                    except Exception as e2:
                        print(f"KnowledgeAgent: error embedding single: {e2}")
                        result.append([])
        return result

    def index_file(self, file_path: str, source_id: Optional[str] = None) -> Tuple[int, Optional[str]]:
        """
        Procesa un archivo (PDF, DOCX o TXT), genera embeddings y los añade a la base.
        source_id: identificador opcional (ej. chat_id o nombre lógico).
        Devuelve (número de chunks indexados, mensaje de error si hubo).
        """
        path = Path(file_path)
        if path.suffix.lower() not in DOC_EXTENSIONS:
            ext = ",".join(DOC_EXTENSIONS)
            return 0, f"Formato no soportado. Use: {ext}"
        text = extract_text_from_file(file_path)
        if not text or not text.strip():
            return 0, "No se pudo extraer texto del archivo."
        chunks = _chunk_text(text)
        if not chunks:
            return 0, "El documento no generó fragmentos para indexar."
        source_label = source_id or path.name
        embeddings = self._embed_texts(chunks)
        added = 0
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            if not emb:
                continue
            self._embeddings.append(emb)
            self._metadata.append({
                "source": source_label,
                "file_path": str(path),
                "text": chunk,
                "chunk_index": i,
            })
            added += 1
        if added > 0:
            self._save_db()
        return added, None

    def search(self, query: str, top_k: int = 5) -> List[dict]:
        """
        Búsqueda semántica en la base vectorial.
        Devuelve una lista de dicts con "text", "source", "score" (similitud coseno).
        """
        if not self._embeddings or not query.strip():
            return []
        import numpy as np
        query_embeddings = self._embed_texts([query.strip()])
        if not query_embeddings or not query_embeddings[0]:
            return []
        q = np.array(query_embeddings[0], dtype=np.float32)
        scores = []
        for emb in self._embeddings:
            v = np.array(emb, dtype=np.float32)
            norm_q = np.linalg.norm(q)
            norm_v = np.linalg.norm(v)
            if norm_q == 0 or norm_v == 0:
                scores.append(0.0)
            else:
                scores.append(float(np.dot(q, v) / (norm_q * norm_v)))
        idx = np.argsort(scores)[::-1][:top_k]
        idx = np.atleast_1d(idx)
        return [
            {
                "text": self._metadata[int(i)].get("text", ""),
                "source": self._metadata[int(i)].get("source", ""),
                "score": float(scores[int(i)]),
            }
            for i in idx
        ]


# Corregir typo en el método search (scores.append float -> scores.append(float))