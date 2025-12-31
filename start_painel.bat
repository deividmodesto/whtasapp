@echo off
cd /d "C:\SaaS"
python -m streamlit run app.py --server.port 8501 --server.headless true