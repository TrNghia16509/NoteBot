
import streamlit as st
import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from pydub import AudioSegment
from streamlit_webrtc import webrtc_streamer, WebRtcMode
import tempfile
import wave
import numpy as np
import queue
import threading
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
from io import BytesIO
from flask import Flask, request, jsonify

#================================ Ghi âm (backend) =========================
flask_app = Flask(__name__)

def process_audio_backend(filepath):
    model = WhisperModel("small", compute_type="int8")
    segments, info = model.transcribe(filepath, language="vi")
    full_text = "\n".join([seg.text for seg in segments])
    subject = genai.GenerativeModel("gemini-1.5-flash").generate_content("Chủ đề chính là gì?\n" + full_text).text.strip()
    summary = genai.GenerativeModel("gemini-1.5-flash").generate_content("Tóm tắt:\n" + full_text).text.strip()
    return subject, summary, full_text

@flask_app.route("/upload_audio", methods=["POST"])
def upload_audio():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        file.save(tmp.name)
        subject, summary, full_text = process_audio_backend(tmp.name)
        return jsonify({
            "subject": subject,
            "summary": summary,
            "text": full_text
        })

import threading
threading.Thread(target=lambda: flask_app.run(port=8000), daemon=True).start()

# ========= Cấu hình =========
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

# ========= Cơ sở dữ liệu =========
conn = sqlite3.connect("notes.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, password TEXT, email TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS notes (
    username TEXT, title TEXT, subject TEXT, summary TEXT, content TEXT, timestamp TEXT, note TEXT)''')
conn.commit()

# ========= Tiêu đề và logo =========
st.set_page_config(page_title="NoteBot", layout="wide")
col1, col2 = st.columns([1, 5])
with col1:
    st.image("https://raw.githubusercontent.com/TrNghia16509/NoteBot/main/logo%20Notebot.jpg", width=150)
with col2:
    st.title("NoteBot - Ghi chú thông minh từ nội dung đa phương tiện")

# ========= Sidebar: Đăng nhập / Đăng ký =========
def login():
    with st.sidebar:
        st.subheader("🔐 Đăng nhập")
        u = st.text_input("Tên đăng nhập hoặc email")
        p = st.text_input("Mật khẩu", type="password")
        if st.button("Đăng nhập"):
            row = c.execute("SELECT * FROM users WHERE (username=? OR email=?) AND password=?", (u, u, p)).fetchone()
            if row:
                st.session_state.logged_in = True
                st.session_state.username = row[0]
                st.success("✅ Đăng nhập thành công!")
            else:
                st.error("Sai tài khoản hoặc mật khẩu.")

        if st.button("Quên mật khẩu?"):
            st.info("Vui lòng liên hệ admin để được cấp lại.")

def register():
    with st.sidebar:
        st.subheader("🆕 Đăng ký")
        new_user = st.text_input("Tên đăng nhập mới")
        email = st.text_input("Email")
        pw1 = st.text_input("Mật khẩu", type="password")
        pw2 = st.text_input("Xác nhận mật khẩu", type="password")
        if st.button("Đăng ký"):
            if pw1 != pw2:
                st.warning("❌ Mật khẩu không khớp.")
            else:
                c.execute("INSERT INTO users VALUES (?, ?, ?)", (new_user, pw1, email))
                conn.commit()
                st.success("✅ Đăng ký thành công. Hãy đăng nhập.")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

with st.sidebar:
    st.markdown("## 🔑 Tài khoản")
    menu = st.radio("Chọn chức năng", ["Đăng nhập", "Đăng ký"])
    if menu == "Đăng nhập":
        login()
    else:
        register()

# ========= Hướng dẫn sử dụng =========
with st.expander("📘 Hướng dẫn sử dụng"):
    st.markdown("""
**1. Tải file hoặc ghi âm trực tiếp**
- Hỗ trợ định dạng: .mp3, .wav, .pdf, .docx

**2. Chọn ngôn ngữ**
- Gợi ý đúng ngôn ngữ của bài giảng để chuyển văn bản chính xác hơn

**3. Tóm tắt, lưu và hỏi đáp**
- Có thể hỏi thêm về nội dung thông qua Chatbox thông minh

**4. Ghi chú**
- Nếu chưa đăng nhập, ghi chú sẽ tạm thời và xóa khi đóng web
- Nếu đã đăng nhập, có thể lưu ghi chú vào hệ thống
""")

# ========= Chọn ngôn ngữ =========
lang = st.selectbox("🌍 Chọn ngôn ngữ đầu vào", ["auto", "vi", "en", "fr", "ja"])

#=========== Ghi âm (frontend) ===========
st.markdown("""
### 🎙 Ghi âm trực tiếp bằng trình duyệt

<button onclick="startRecording()">🎙 Bắt đầu ghi âm</button>
<button onclick="stopRecording()">⏹ Dừng và gửi</button>
<audio id="audioPlayback" controls></audio>

<script>
let mediaRecorder;
let audioChunks = [];

function startRecording() {
    audioChunks = [];
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.start();

        mediaRecorder.addEventListener("dataavailable", event => {
            audioChunks.push(event.data);
        });

        mediaRecorder.addEventListener("stop", () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
            const audioUrl = URL.createObjectURL(audioBlob);
            document.getElementById("audioPlayback").src = audioUrl;

            const formData = new FormData();
            formData.append("file", audioBlob, "recorded.wav");

            fetch("/upload_audio", {
                method: "POST",
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                alert("📌 Chủ đề: " + data.subject + "\\n📝 Tóm tắt: " + data.summary);
            })
            .catch(error => alert("❌ Lỗi gửi ghi âm: " + error));
        });
    });
}

function stopRecording() {
    mediaRecorder.stop();
}
</script>
""", unsafe_allow_html=True)

# ========= Tải file hoặc ghi âm =========
uploaded_file = st.file_uploader("📤 Tải lên file (.mp3, .wav, .pdf, .docx)", type=["mp3", "wav", "pdf", "docx"])

def transcribe_audio(file, language="vi"):
    model = WhisperModel("small", compute_type="int8")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(file.read())
        tmp_path = tmp.name
    segments, info = model.transcribe(tmp_path, language=None if language == "auto" else language)
    os.remove(tmp_path)
    return "\n".join([seg.text for seg in segments]), info.language

def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = "\n".join([page.get_text() for page in doc])
    return text

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

# ========= Phân loại và xử lý =========
text_result = ""
if uploaded_file:
    if uploaded_file.name.endswith(".pdf"):
        text_result = extract_text_from_pdf(uploaded_file)
    elif uploaded_file.name.endswith(".docx"):
        text_result = extract_text_from_docx(uploaded_file)
    else:
        text_result, lang_detected = transcribe_audio(uploaded_file, language=lang)
    st.success("✅ Nội dung đã xử lý:")
    st.text_area("📄 Nội dung", text_result, height=300)

    # Tóm tắt và AI xử lý
    model = genai.GenerativeModel("gemini-1.5-flash")
    subject_prompt = f"Chủ đề chính của nội dung sau là gì? {text_result}"
    
    subject = model.generate_content(subject_prompt).text.strip()

    summary_prompt = f"Bạn là chuyên gia về {subject}. Tóm tắt nội dung: {text_result}"
    summary = model.generate_content(summary_prompt).text.strip()

    st.subheader("📚 Tóm tắt bởi AI")
    st.write(summary)

    # Chatbot
    st.markdown("### 🤖 Hỏi gì thêm về nội dung?")
    if "chat" not in st.session_state:
        st.session_state.chat = []
    for msg in st.session_state.chat:
        st.chat_message(msg["role"]).write(msg["content"])
    q = st.chat_input("Nhập câu hỏi...")
    if q:
        st.chat_message("user").write(q)
        ai = model.start_chat(history=[{"role": "user", "parts": text_result}])
        r = ai.send_message(q)
        st.chat_message("assistant").write(r.text)
        st.session_state.chat.append({"role": "user", "content": q})
        st.session_state.chat.append({"role": "assistant", "content": r.text})

    # Ghi chú và lưu
    title = subject
    note = st.text_input("📝 Ghi chú thêm")
    if st.session_state.logged_in:
        if st.button("💾 Lưu ghi chú"):
            c.execute("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?)", (
                st.session_state.username, title, subject, summary, text_result,
                datetime.now().isoformat(), note
            ))
            conn.commit()
            st.success("Đã lưu!")
    else:
        st.info("🔒 Ghi chú tạm thời - hãy đăng nhập để lưu vĩnh viễn")

# ========= Hiển thị ghi chú =========
if st.session_state.logged_in:
    st.subheader("📂 Ghi chú đã lưu")
    rows = c.execute("SELECT title, summary, timestamp, note FROM notes WHERE username=?", (st.session_state.username,)).fetchall()
    for r in rows:
        with st.expander(f"📝 {r[0]} ({r[2][:10]})"):

            st.markdown(f"**Tóm tắt:** {r[1]}")
            st.markdown(f"**Ghi chú:** {r[3]}")
