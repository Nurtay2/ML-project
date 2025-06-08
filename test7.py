import os
import json
import io
import re
import requests
import pandas as pd
import streamlit as st
import docx

STATUS_CHOICES = ['new', 'in_progress', 'completed', 'cancelled']
PRIORITY_CHOICES = ['low', 'medium', 'high', 'critical']

def extract_text_from_docx(file):
    try:
        doc = docx.Document(file)
    except Exception as e:
        st.error(f"Не удалось открыть DOCX: {e}")
        return ""
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)

def normalize_json_result(data, student_name, role_ru):
    if not isinstance(data, dict):
        raise ValueError(f"Ответ не является JSON-объектом для {student_name}")
    data["role"] = str(role_ru)
    data["executor"] = str(student_name)
    data["author"] = "AI"
    if data.get("status") not in STATUS_CHOICES:
        data["status"] = "new"
    if data.get("priority") not in PRIORITY_CHOICES:
        data["priority"] = "medium"
    for key in ["title", "description"]:
        if isinstance(data.get(key), str):
            data[key] = data[key].replace('\n', ' ').replace('\r', ' ').strip()
    return data

def extract_json_from_text(text):
    match = re.search(r'({.*})', text, re.DOTALL)
    if match:
        return match.group(1)
    return text

CACHE = {}

def cache_key(document_text, student_name, role_ru, model):
    import hashlib
    key_base = f"{document_text[:1000]}||{student_name}||{role_ru}||{model}"
    return hashlib.md5(key_base.encode("utf-8")).hexdigest()

def generate_task_json(document_text, student_name, role_ru, api_key, model="mistral-small", used_titles=None):
    # Новый system_prompt с учётом специфики ролей
    system_prompt = (
        "Ты — ассистент по генерации индивидуальных задач для студентов, работающих над проектом в команде. "
        "Для каждого студента придумай одну уникальную задачу, подходящую именно для его роли (например, Аналитик, Тестировщик, Менеджер, Дизайнер). "
        "Используй специфику роли:\n"
        "- Аналитик: задачи по анализу требований, ТЗ, исследованию предметной области.\n"
        "- Тестировщик: задачи по тестированию, написанию тест-кейсов, поиску багов, отчётности о дефектах.\n"
        "- Менеджер: задачи по координации, контролю сроков, коммуникации, распределению задач.\n"
        "- Дизайнер: задачи по макетам, прототипам, UI/UX, подготовке графических материалов.\n"
        "Ответ — строго ОДИН JSON без текста вокруг. Поля:\n"
        "{"
        "\"title\": \"Коротко, до 5 слов\","
        "\"description\": \"Подробное, без \\n, структурированное описание, на русском\","
        "\"status\": \"new | in_progress | completed | cancelled\","
        "\"priority\": \"low | medium | high | critical\","
        "\"role\": \"роль на русском\","
        "\"executor\": \"полное имя студента\","
        "\"author\": \"AI\""
        "}\n"
        "Никаких пояснений, ровно один JSON. Не повторяй формулировки между студентами, особенно title и description."
    )
    user_prompt = (
        f"Техническое задание:\n{document_text}\n\n"
        f"Студент: {student_name}\n"
        f"Роль: {role_ru}\n"
        "Придумай индивидуальную задачу, максимально подходящую для этой роли. "
        "Задача должна быть уникальной (не совпадать с предыдущими), релевантной компетенциям студента и подробно описанной. "
        "Верни строго валидный JSON. Без комментариев и постороннего текста!"
    )
    # Мемо-кэш
    key = cache_key(document_text, student_name, role_ru, model)
    if key in CACHE:
        return CACHE[key]
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ]
    }
    response = requests.post(url, json=payload, headers=headers, timeout=90)
    response.raise_for_status()
    raw_text = response.json()["choices"][0]["message"]["content"].strip()
    raw_json = extract_json_from_text(raw_text)
    try:
        data = json.loads(raw_json)
    except Exception as e:
        raise ValueError(f"Ошибка JSON для {student_name}:\n{raw_text}\nОшибка: {e}")
    data = normalize_json_result(data, student_name, role_ru)
    # Делаем title уникальным если надо
    if used_titles is not None:
        title_key = (data["title"], data["description"])
        if title_key in used_titles:
            # Добавим уникализатор к title
            data["title"] = f"{data['title']} [{role_ru}]"
        used_titles.add((data["title"], data["description"]))
    CACHE[key] = data
    return data

# ---- Streamlit UI ----

st.set_page_config(page_title="Генерация задач через Mistral.ai", layout="wide")
st.title("📝 Генерация задач для студентов (Mistral.ai + Streamlit)")

st.markdown("""
**Как пользоваться**:
1. Загрузите DOCX файл с техническим заданием.
2. Загрузите CSV со списком студентов и их ролями.
3. Укажите API-ключ для Mistral.ai.
4. Нажмите **«Сгенерировать задачи»**.
""")

with st.expander("Пример структуры CSV"):
    st.code(
        """student_name,role
Иван Иванов,Analyst
Мария Петрова,Tester
Алексей Смирнов,Manager
Екатерина Сидорова,Designer
""", language="csv"
    )

st.sidebar.header("Настройки API")
api_key_input = st.sidebar.text_input("API-ключ Mistral.ai", value=os.getenv("MISTRAL_API_KEY", ""), type="password")
model_choice = st.sidebar.selectbox("Выберите модель Mistral", options=["mistral-small", "mistral-base", "mistral-large"], index=0)

st.header("1. Загрузите файлы")
col1, col2 = st.columns(2)

with col1:
    uploaded_docx = st.file_uploader("Загрузите DOCX с техническим заданием", type=["docx"])
with col2:
    uploaded_csv = st.file_uploader("Загрузите CSV со студентами и ролями", type=["csv"])

generate_button = st.button("▶ Сгенерировать задачи")

if generate_button:
    if not uploaded_docx:
        st.error("❗ Пожалуйста, загрузите DOCX файл с ТЗ.")
    elif not uploaded_csv:
        st.error("❗ Пожалуйста, загрузите CSV со студентами и ролями.")
    else:
        api_key = api_key_input.strip() or os.getenv("MISTRAL_API_KEY", "")
        if not api_key:
            st.error("❗ API-ключ не задан.")
        else:
            with st.spinner("Извлекаем текст из DOCX..."):
                try:
                    document_text = extract_text_from_docx(uploaded_docx)
                except Exception as e:
                    st.error(f"Ошибка при чтении DOCX: {e}")
                    document_text = ""
            if not document_text:
                st.error("❗ Не удалось получить текст из DOCX.")
            else:
                with st.spinner("Загружаем список студентов и ролей..."):
                    try:
                        df_students = pd.read_csv(uploaded_csv)
                    except Exception as e:
                        st.error(f"Не удалось прочитать CSV: {e}")
                        df_students = pd.DataFrame()
                if df_students.empty or "student_name" not in df_students.columns or "role" not in df_students.columns:
                    st.error("❗ Неверная структура CSV. Должны быть колонки `student_name` и `role`.")
                else:
                    role_mapping = {
                        "Analyst":  "Аналитик",
                        "Tester":   "Тестировщик",
                        "Manager":  "Менеджер",
                        "Designer": "Дизайнер"
                    }
                    df_students["role_ru"] = df_students["role"].map(lambda r: role_mapping.get(r, r))
                    st.info("🔄 Генерация задач через Mistral.ai")
                    progress_bar = st.progress(0)
                    total = len(df_students)
                    results = []
                    errors = []
                    used_titles = set()
                    for idx, row in df_students.iterrows():
                        student_name = str(row["student_name"]).strip()
                        role_ru = str(row["role_ru"]).strip()
                        try:
                            task_json = generate_task_json(
                                document_text=document_text,
                                student_name=student_name,
                                role_ru=role_ru,
                                api_key=api_key,
                                model=model_choice,
                                used_titles=used_titles
                            )
                            results.append(task_json)
                        except Exception as e:
                            errors.append(f"{student_name} ({role_ru}): {e}")
                        progress_bar.progress((idx + 1) / total)
                    st.success(f"Генерация завершена: {len(results)} из {total} задач успешно получены.")
                    if errors:
                        with st.expander("Ошибки генерации"):
                            for err in errors:
                                st.write(f"- {err}")
                    if results:
                        df_out = pd.DataFrame(results)
                        df_out = df_out.rename(columns={
                            "title":       "Название задачи",
                            "description": "Описание задачи",
                            "status":      "Статус",
                            "priority":    "Приоритет",
                            "role":        "Роль",
                            "executor":    "Исполнитель",
                            "author":      "Автор"
                        })
                        st.dataframe(df_out)
                        csv_bytes = df_out.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                        st.download_button(
                            label="⬇ Скачать CSV с задачами",
                            data=csv_bytes,
                            file_name="tasks_output.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning("❗ Ни одна задача не была сгенерирована. Проверьте ошибки выше.")
# Streamlit app for generating tasks using Mistral.ai
# This code is a Streamlit application that allows users to generate tasks for students based on a technical document and a list of students with their roles.