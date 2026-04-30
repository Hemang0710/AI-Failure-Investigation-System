#!/bin/bash
cd /app
python -m streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
