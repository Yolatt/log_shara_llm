import os
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# ==========================================
# НАСТРОЙКИ
# ==========================================
LOG_DIRECTORY = r"d:\log_shara_llm\logs"  # <-- ЗАМЕНИТЕ НА ПУТЬ К ВАШЕЙ ПАПКЕ
LM_STUDIO_URL = "http://localhost:1234/api/v1/chat"

# ВАЖНО: Имя модели должно точно совпадать с тем, как она называется в LM Studio.
# Обычно это название репозитория или папки. Если LM Studio выдаст ошибку "Model not found",
# скопируйте точное имя из вкладки Local Server в LM Studio.
MODEL_NAME = "bartowski/gemma-2-27b-it-GGUF" 

DEFAULT_SYSTEM_PROMPT = """Ты — старший сотрудник службы информационной безопасности (SOC). 
Твоя задача — просматривать логи и докладывать о найденных угроза\инцидентах
Правила:
1. Отвечай строго на основе предоставленного контекста. Не выдумывай события.
2. Если в логах есть ошибки, укажи точное время, IP-адрес, имя пользователя и тип события.
3. Если аномалий не обнаружено, так и напиши: "Критических аномалий не выявлено".
4. Отвечай на русском языке, но технические термины оставляй на английском."""

if not os.path.isdir(LOG_DIRECTORY):
    raise ValueError(f"Папка с логами не найдена: {LOG_DIRECTORY}")

# --- ИНИЦИАЛИЗАЦИЯ EMBEDDINGS ---
print("Загрузка модели эмбеддингов...")
Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

index = None

def load_documents():
    print(f"Чтение файлов из: {LOG_DIRECTORY}")
    documents = SimpleDirectoryReader(LOG_DIRECTORY).load_data()
    print(f"Загружено документов: {len(documents)}. Построение индекса...")
    return VectorStoreIndex.from_documents(documents)

print("Инициализация индекса...")
index = load_documents()
print("Готово к работе!")

# --- FASTAPI ---
app = FastAPI(title="Log Analysis API (LM Studio Native)")

class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    system_prompt: Optional[str] = None  # Можно переопределить системный промпт через API

@app.post("/query")
async def query_logs(request: QueryRequest):
    if not index:
        raise HTTPException(status_code=500, detail="Индекс не инициализирован")
    
    # 1. ПОИСК (Retrieval): Находим релевантные куски логов
    retriever = index.as_retriever(similarity_top_k=request.top_k)
    nodes = retriever.retrieve(request.question)
    
    if not nodes:
        return {"question": request.question, "answer": "В логах не найдено информации, релевантной вашему запросу.", "sources": []}

    # Склеиваем найденные куски в один текст
    context_str = "\n\n---\n\n".join([node.get_content() for node in nodes])
    
    # 2. ФОРМИРОВАНИЕ ПРОМПТА
    prompt = f"КОНТЕКСТ (ФРАГМЕНТЫ ЛОГОВ):\n{context_str}\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ: {request.question}\n\nТВОЙ ОТВЕТ:"
    
    # 3. ФОРМИРОВАНИЕ PAYLOAD СТРОГО ПО ДОКУМЕНТАЦИИ LM STUDIO /api/v1/chat
    payload = {
        "model": MODEL_NAME,
        "input": prompt,
        "system_prompt": request.system_prompt or DEFAULT_SYSTEM_PROMPT,
        "temperature": 0.1,
        "context_length": 8192,
        "stream": False
    }
    
    # 4. ОТПРАВКА ЗАПРОСА В LM STUDIO
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(LM_STUDIO_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            
            # 5. ПАРСИНГ ОТВЕТА (согласно документации: output - это массив объектов)
            answer = ""
            if "output" in data:
                for item in data["output"]:
                    if item.get("type") == "message":
                        answer += item.get("content", "")
            
            return {
                "question": request.question,
                "answer": answer,
                "sources": [
                    {
                        "file": node.metadata.get("file_name", "Unknown"),
                        "snippet": node.text[:200] + "..."
                    } for node in nodes
                ],
                "stats": data.get("stats", {})  # Возвращаем статистику (токены, скорость) из ответа LM Studio
            }
            
    except httpx.HTTPStatusError as e:
        # Если LM Studio вернул ошибку (например, неверное имя модели)
        raise HTTPException(status_code=502, detail=f"Ошибка от LM Studio: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {str(e)}")

@app.post("/reload")
async def reload_logs():
    global index
    try:
        index = load_documents()
        return {"status": "success", "message": "Логи успешно переиндексированы"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    print("Запуск API на http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)




    # Формируем JSON
$body = @{
    question = "Найди угрозы\инциденты в предоставленных логах"
} | ConvertTo-Json -Compress

# Кодируем в UTF-8 и отправляем
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post -Body $bytes -ContentType "application/json; charset=utf-8"