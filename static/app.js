const status = document.getElementById('status');
const recognizedDiv = document.getElementById('recognized');
const translatedDiv = document.getElementById('translated');
let mediaRecorder;
let audioChunks = [];
let currentLang = 'ru';
let isRecording = false;
let audioStream = null;

let recordStartTime = 0;
let ignoreRecording = false;

const globalPlayer = new Audio();
let isPlayerUnlocked = false;

// ==========================================
// 1. ADVANCED TELEMETRY (Model, OS, Network)
// ==========================================
async function getTelemetryData() {
    let network = navigator.connection ? navigator.connection.effectiveType.toUpperCase() : 'UNKNOWN';
    let platform = 'Unknown OS';
    let model = 'Unknown Device';

    // Попытка использовать современный API (Chrome на Android)
    if (navigator.userAgentData) {
        platform = navigator.userAgentData.platform;
        try {
            const highEntropy = await navigator.userAgentData.getHighEntropyValues(['model']);
            if (highEntropy.model) {
                model = highEntropy.model;
            }
        } catch (e) {
            console.warn("Client Hints blocked");
        }
    }

    // Резервный вариант для старых браузеров и iOS
    if (model === 'Unknown Device') {
        const ua = navigator.userAgent;
        if (/android/i.test(ua)) {
            platform = 'Android';
            // Вытаскиваем точную модель телефона после версии Android
            const match = ua.match(/Android\s+[0-9\.]+;\s+([^;)]+)/);
            if (match && match[1]) {
                model = match[1].trim();
            }
        } else if (/iphone/i.test(ua)) {
            platform = 'iOS';
            model = 'iPhone';
        } else if (/ipad/i.test(ua)) {
            platform = 'iOS';
            model = 'iPad';
        } else if (/mac/i.test(ua)) {
            platform = 'macOS';
            model = 'Mac';
        } else if (/windows/i.test(ua)) {
            platform = 'Windows';
            model = 'PC';
        }
    }

    // Возвращаем данные с переносом строки (\n)
    return `📱 Model: ${platform} ${model}\n📶 Network: ${network}`;
}

// ==========================================
// 2. ИНИЦИАЛИЗАЦИЯ МИКРОФОНА (СЫРОЙ ЗВУК ДЛЯ ИИ)
// ==========================================
async function initMicrophone() {
    try {
        const audioConstraints = {
            audio: {
                // ОТКЛЮЧАЕМ ВСЕ ФИЛЬТРЫ - Whisper сам лучше справится с шумом
                echoCancellation: false,      
                noiseSuppression: false,      
                autoGainControl: false,       
                sampleRate: 48000, // Пишем в максимальном качестве, Groq сам ужмет как надо
                channelCount: 1
            }
        };
        audioStream = await navigator.mediaDevices.getUserMedia(audioConstraints);
    } catch (err) {
        status.innerText = "Ошибка доступа к микрофону!";
        console.error(err);
    }
}
initMicrophone();

// ==========================================
// 3. ЛОГИКА ЗАПИСИ
// ==========================================
async function startRec(lang, e) {
    e.preventDefault();

    // Разблокировка iOS аудио
    if (!isPlayerUnlocked) {
        globalPlayer.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
        globalPlayer.play().catch(err => console.log("Unlock failed", err));
        isPlayerUnlocked = true;
    }

    if (isRecording) return;

    // Проверка микрофона после сна
    if (!audioStream || !audioStream.active || audioStream.getAudioTracks()[0].readyState === 'ended') {
        status.innerText = "Будим микрофон...";
        await initMicrophone();
        if (!audioStream) return;
    }

    currentLang = lang;
    isRecording = true;
    ignoreRecording = false;
    recordStartTime = Date.now();
    audioChunks = [];

    let options = { audioBitsPerSecond: 128000 };
    let ext = 'webm';
    
    if (MediaRecorder.isTypeSupported('audio/webm')) {
        options.mimeType = 'audio/webm';
    } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
        options.mimeType = 'audio/mp4';
        ext = 'mp4'; 
    }

    mediaRecorder = new MediaRecorder(audioStream, options);
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };

    mediaRecorder.onstop = async () => {
        if (ignoreRecording) {
            audioChunks = [];
            return;
        }

        status.innerText = "Обработка (Groq + TTS)...";
        const audioBlob = new Blob(audioChunks, options);
        audioChunks = [];

        const formData = new FormData();
        formData.append('audio', audioBlob, 'record.' + ext);
        formData.append('source_lang', currentLang);
        
        // ВСТАВЛЯЕМ НАШУ КРАСИВУЮ ТЕЛЕМЕТРИЮ
        const telemetry = await getTelemetryData();
        formData.append('device_info', telemetry);

        try {
            const response = await fetch('/api/translate-voice', { method: 'POST', body: formData });
            if (!response.ok) throw new Error(await response.text());

            recognizedDiv.innerText = JSON.parse('"' + (response.headers.get("X-Recognized-Text") || "") + '"');
            translatedDiv.innerText = JSON.parse('"' + (response.headers.get("X-Translated-Text") || "") + '"');

            const audioUrl = URL.createObjectURL(await response.blob());
            globalPlayer.src = audioUrl;
            globalPlayer.play();

            status.innerText = "Готово!";
        } catch (err) {
            status.innerText = "Ошибка обработки";
            console.error(err);
        }
    };

    mediaRecorder.start();
    (lang === 'ru' ? document.getElementById('btnRu') : document.getElementById('btnLt')).classList.add('recording');
    status.innerText = "Слушаю... Отпустите для перевода";
}

function stopRec(e) {
    e.preventDefault();
    if (!isRecording || !mediaRecorder) return;

    const duration = Date.now() - recordStartTime;
    if (duration < 500) {
        ignoreRecording = true;
        status.innerText = "Слишком короткое нажатие";
        setTimeout(() => { if (!isRecording) status.innerText = "Зажмите кнопку нужного языка"; }, 1500);
    }

    if (mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        document.getElementById('btnRu').classList.remove('recording');
        document.getElementById('btnLt').classList.remove('recording');
        isRecording = false;
    }
}

// Привязываем события для Touch (мобильные) и Mouse (ПК)
const btnRu = document.getElementById('btnRu');
const btnLt = document.getElementById('btnLt');

btnRu.addEventListener('mousedown', (e) => startRec('ru', e));
btnRu.addEventListener('touchstart', (e) => startRec('ru', e));
btnRu.addEventListener('mouseup', stopRec);
btnRu.addEventListener('touchend', stopRec);

btnLt.addEventListener('mousedown', (e) => startRec('lt', e));
btnLt.addEventListener('touchstart', (e) => startRec('lt', e));
btnLt.addEventListener('mouseup', stopRec);
btnLt.addEventListener('touchend', stopRec);
