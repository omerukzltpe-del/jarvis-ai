#!/bin/bash
echo "================================"
echo "  J.A.R.V.I.S. Kurulum Basliyor"
echo "================================"
echo ""

# API anahtarını kontrol et
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "UYARI: ANTHROPIC_API_KEY bulunamadi!"
    echo ""
    read -p "Anthropic API anahtarinizi girin: " API_KEY
    export ANTHROPIC_API_KEY=$API_KEY
fi

# Mac için portaudio kur
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Mac icin portaudio kuruluyor..."
    brew install portaudio 2>/dev/null || echo "(brew yoksa atlandi)"
fi

# Linux için portaudio kur
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "Linux icin portaudio kuruluyor..."
    sudo apt-get install -y portaudio19-dev python3-pyaudio 2>/dev/null || true
fi

# Python paketlerini yükle
echo "Python paketleri yukleniyor..."
pip install anthropic SpeechRecognition pyttsx3 pyaudio

echo ""
echo "================================"
echo "  J.A.R.V.I.S. Baslatiliyor..."
echo "================================"
python3 jarvis.py
