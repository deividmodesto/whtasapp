module.exports = {
  apps : [
    {
      name: "Evolution-API",
      cwd: "C:\\SaaS\\evolution-api", // <--- Caminho corrigido!
      script: "C:\\Windows\\System32\\cmd.exe",
      args: "/c npm run start:prod",
      interpreter: "none",
      autorestart: true,
      watch: false
    },
    {
      name: "API-Backend",
      script: "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe",
      args: "-m uvicorn main:app --host 0.0.0.0 --port 8000",
      cwd: "C:\\SaaS", 
      interpreter: "none",
      autorestart: true,
      watch: false,
    },
    {
      name: "Painel-Streamlit",
      script: "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe",
      args: "-m streamlit run app.py --server.port 8501 --server.headless true",
      cwd: "C:\\SaaS",
      interpreter: "none",
      autorestart: true,
      watch: false,
    }
  ]
};