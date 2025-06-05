# app.py

import os
import json
import io
import requests
import pandas as pd
import streamlit as st
import docx

# -----------------------------
# Функции для работы с DOCX и API
# -----------------------------

def extract_text_from_docx(file):
    """
    Извлекает и возвращает весь текст из DOCX-файла (file может быть шляхом к файлу или file-like-объектом),
    объединяя непустые параграфы через перенос строки.
    """
    # Если передано не файловый объект, пробуем открыть как путь
    try:
        doc = docx.Document(file)
    except Exception as e:
        st.error(f"Не удалось открыть DOCX: {e}")
        return ""
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def generate_task_json(document_text: str, student_name: str, role_ru: str, api_key: str, model: str = "mistral-small"):
    """
    Отправляет запрос к Mistral API, чтобы сгенерировать одну задачу для конкретного студента.
    Ожидает ответ в виде валидного JSON-объекта с шестью полями:
      {
        "title": "<короткий заголовок, не более 5 слов>",
        "description": "<подробное описание задачи на русском>",
        "status": "Todo",
        "role": "<роль студента на русском>",
        "executor": "<полное имя студента>",
        "author": "AI"
      }
    """
    if not api_key:
        raise ValueError("API-ключ Mistral не задан.")

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # Системное сообщение: строгий формат только JSON
    system_prompt = (
        "Ты — ассистент, который на основе технического задания формирует одну задачу для конкретного студента.\n"
        "Тебе необходимо вернуть строго один JSON-объект (никаких текстовых описаний) с точно шестью полями:\n"
        "  {\n"
        "    \"title\": \"<короткий заголовок, не более 5 слов, без лишних символов>\",\n"
        "    \"description\": \"<подробное описание задачи на литературном русском>\",\n"
        "    \"status\": \"Todo\",\n"
        "    \"role\": \"<роль студента на русском, напр. Аналитик>\",\n"
        "    \"executor\": \"<полное имя студента>\",\n"
        "    \"author\": \"AI\"\n"
        "  }\n"
        "Критерии:\n"
        "- title: не более пяти слов, без кавычек внутри, без переносов строк.\n"
        "- description: литературный русский, может быть длинным, но без символов '\\n' внутри.\n"
        "- status всегда \"Todo\".\n"
        "- role — слово на русском.\n"
        "- executor — строка с полным именем студента.\n"
        "- author — строка \"AI\".\n"
        "Никаких дополнительных полей, никаких комментариев, ровно один JSON."
    )

    # Сообщение с текстом ТЗ, именем студента и ролью
    user_prompt = (
        f"Техническое задание:\n{document_text}\n\n"
        f"Студент: {student_name}\n"
        f"Роль: {role_ru}\n"
        "Пожалуйста, верни JSON с задачей."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ]
    }

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    raw_text = response.json()["choices"][0]["message"]["content"].strip()

    # Разбор JSON
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Не удалось распарсить JSON от LLM для {student_name}:\n{raw_text}\nОшибка: {e}")

    # Проверка полей
    required_fields = {"title", "description", "status", "role", "executor", "author"}
    if not required_fields.issubset(set(data.keys())):
        raise ValueError(f"В JSON для {student_name} отсутствуют обязательные поля:\n{raw_text}")

    return data


# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(
    page_title="Генерация задач через Mistral.ai",
    layout="wide"
)

st.title("📝 Генерация задач для студентов (Mistral.ai + Streamlit)")
st.markdown(
    """
    **Как пользоваться**:
    1. Загрузите DOCX файл с техническим заданием.
    2. Загрузите CSV со списком студентов и их ролями (есть пример ниже).
    3. Укажите ваш API-ключ для Mistral.ai (можно воспользоваться переменной окружения `MISTRAL_API_KEY`).
    4. Нажмите **«Сгенерировать задачи»** и дождитесь окончания обработки.
    5. После генерации вы сможете скачать готовый CSV с полями:
       `Название задачи`, `Описание задачи`, `Статус`, `Роль`, `Исполнитель`, `Автор`.
    """
)


with st.expander("Пример структуры CSV (students_roles_random.csv)"):
    st.code(
        """student_name,role
Иван Иванов,Analyst
Мария Петрова,Tester
Алексей Смирнов,Manager
Екатерина Сидорова,Designer
""", language="csv"
    )

# --- 1. Ввод API-ключа ---
st.sidebar.header("Настройки API")
api_key_input = st.sidebar.text_input(
    "API-ключ Mistral.ai",
    value=os.getenv("MISTRAL_API_KEY", ""),
    type="password",
    help="Если не заполнить, будет взято из переменной окружения MISTRAL_API_KEY"
)

model_choice = st.sidebar.selectbox(
    "Выберите модель Mistral",
    options=["mistral-small", "mistral-base", "mistral-large"],
    index=0,
    help="Введите название модели так, как оно зарегистрировано в Mistral.ai"
)

# --- 2. Загрузка файлов ---
st.header("1. Загрузите файлы")
col1, col2 = st.columns(2)

with col1:
    uploaded_docx = st.file_uploader(
        "Загрузите DOCX с техническим заданием",
        type=["docx"],
        help="Файл должен содержать чистый текст в параграфах, без лишних картинок"
    )

with col2:
    uploaded_csv = st.file_uploader(
        "Загрузите CSV со студентами и ролями",
        type=["csv"],
        help="CSV с колонками `student_name,role`. Пример см. выше."
    )

# Кнопка запуска обработки
generate_button = st.button("▶ Сгенерировать задачи")

# -----------------------------
# Логика при нажатии "Сгенерировать задачи"
# -----------------------------
if generate_button:
    if not uploaded_docx:
        st.error("❗ Пожалуйста, загрузите DOCX файл с ТЗ.")
    elif not uploaded_csv:
        st.error("❗ Пожалуйста, загрузите CSV со студентами и ролями.")
    else:
        # Берём API-ключ
        api_key = api_key_input.strip() or os.getenv("MISTRAL_API_KEY", "")
        if not api_key:
            st.error("❗ API-ключ не задан. Установите в поле выше или в переменную окружения.")
        else:
            # -----------------------------
            # Читаем текст из DOCX
            # -----------------------------
            with st.spinner("Извлекаем текст из DOCX..."):
                try:
                    # streamlit file_uploader возвращает io.BytesIO
                    # Поэтому передаём его напрямую
                    document_text = extract_text_from_docx(uploaded_docx)
                except Exception as e:
                    st.error(f"Ошибка при чтении DOCX: {e}")
                    document_text = ""

            if not document_text:
                st.error("❗ Не удалось получить текст из DOCX.")
            else:
                # -----------------------------
                # Читаем CSV студентов
                # -----------------------------
                with st.spinner("Загружаем список студентов и ролей..."):
                    try:
                        df_students = pd.read_csv(uploaded_csv)
                    except Exception as e:
                        st.error(f"Не удалось прочитать CSV: {e}")
                        df_students = pd.DataFrame()

                if df_students.empty or "student_name" not in df_students.columns or "role" not in df_students.columns:
                    st.error("❗ Неверная структура CSV. Должны быть колонки `student_name` и `role`.")
                else:
                    # Преобразуем роли на русский (если они в английском)
                    role_mapping = {
                        "Analyst":  "Аналитик",
                        "Tester":   "Тестировщик",
                        "Manager":  "Менеджер",
                        "Designer": "Дизайнер"
                    }
                    df_students["role_ru"] = df_students["role"].map(lambda r: role_mapping.get(r, r))

                    # -----------------------------
                    # Генерация задач
                    # -----------------------------
                    st.info("🔄 Запущена генерация задач через Mistral.ai")
                    progress_bar = st.progress(0)
                    total = len(df_students)
                    results = []
                    errors = []

                    for idx, row in df_students.iterrows():
                        student_name = str(row["student_name"]).strip()
                        role_ru = str(row["role_ru"]).strip()

                        try:
                            task_json = generate_task_json(
                                document_text=document_text,
                                student_name=student_name,
                                role_ru=role_ru,
                                api_key=api_key,
                                model=model_choice
                            )
                            results.append(task_json)
                        except Exception as e:
                            # Запоминаем ошибку для вывода в лог
                            errors.append(f"{student_name} ({role_ru}): {e}")
                        # Обновляем прогресс
                        progress_bar.progress((idx + 1) / total)

                    # -----------------------------
                    # Отображаем результаты
                    # -----------------------------
                    st.success(f"Генерация завершена: {len(results)} из {total} задач успешно получены.")
                    if errors:
                        with st.expander("Просмотреть ошибки генерации"):
                            for err in errors:
                                st.write(f"- {err}")

                    if results:
                        # Преобразуем в DataFrame и отображаем
                        df_out = pd.DataFrame(results)
                        df_out = df_out.rename(columns={
                            "title":       "Название задачи",
                            "description": "Описание задачи",
                            "status":      "Статус",
                            "role":        "Роль",
                            "executor":    "Исполнитель",
                            "author":      "Автор"
                        })

                        st.dataframe(df_out)

                        # Кнопка для скачивания CSV
                        csv_bytes = df_out.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                        st.download_button(
                            label="⬇ Скачать CSV с задачами",
                            data=csv_bytes,
                            file_name="tasks_output.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning("❗ Ни одна задача не была сгенерирована. Проверьте ошибки выше.")

# -----------------------------
# Подвал с инструкциями
# -----------------------------
st.markdown("---")
st.markdown(
    """
    **Примечания и советы**:
    - Если ваш API-ключ для Mistral.ai большой и вы не хотите вводить его вручную, 
      просто экспортируйте его в окружение перед запуском Streamlit:
      
      ```
      export MISTRAL_API_KEY="ваш_ключ_здесь"
      streamlit run app.py
      ```
    - Функция `extract_text_from_docx` извлекает только текст из параграфов. Если в вашем DOCX есть таблицы или другие сложные объекты — их нужно обрабатывать отдельно.
    - По умолчанию модель `mistral-small` обеспечивает высокую скорость, но при необходимости можно выбрать более мощную модель (например, `mistral-base`).
    - Если количество студентов большое, генерация может занять значительное время: 
      следите за прогресс-баром и будьте уверены, что интернет-соединение стабильно.
    """
)
