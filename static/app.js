class VoiceTranslator {
    constructor() {
        // UI Elements
        this.ui = {
            status: document.getElementById('status'),
            recognized: document.getElementById('recognized'),
            translated: document.getElementById('translated'),
            btnTop: document.getElementById('btnTop'),
            btnBottom: document.getElementById('btnBottom'),
            btnTopLabel: document.getElementById('btnTopLabel'),
            btnBottomLabel: document.getElementById('btnBottomLabel'),
            pairSelector: document.getElementById('langPairSelector'),
            dotSource: document.getElementById('dotSource'),
            dotTarget: document.getElementById('dotTarget')
        };

        // Конфигурация языков
        this.langConfig = {
            'ru': { flag: '🇷🇺', name: 'RU', color: '#10b981' }, // Изумрудный
            'lt': { flag: '🇱🇹', name: 'LT', color: '#3b82f6' }, // Сапфировый
            'pl': { flag: '🇵🇱', name: 'PL', color: '#ef4444' }  // Красный
        };

        // Application State
        this.state = {
            isRecording: false,
            currentSource: 'ru',
            currentTarget: 'lt',
            recordStartTime: 0,
            ignoreRecording: false
        };

        // Media, Sockets & Audio Context
        this.mediaRecorder = null;
        this.audioStream = null;
        this.ws = null;

        // Магия Web Audio API (Решает проблему "проглоченных" слов на телефонах)
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        this.audioCtx = new AudioContext();

        this.init();
    }

    // Initialize application
    init() {
        this.bindEvents();
        this.updateUIPair();
        this.initMicrophone();
    }

    bindEvents() {
        this.ui.pairSelector.addEventListener('change', () => this.updateUIPair());

        [this.ui.btnTop, this.ui.btnBottom].forEach(btn => {
            btn.addEventListener('contextmenu', e => e.preventDefault());
        });

        this.ui.btnTop.addEventListener('pointerdown', (e) => {
            const [lang1, lang2] = this.ui.pairSelector.value.split('-');
            this.startRecording(lang1, lang2, this.ui.btnTop, e);
        });

        this.ui.btnBottom.addEventListener('pointerdown', (e) => {
            const [lang1, lang2] = this.ui.pairSelector.value.split('-');
            this.startRecording(lang2, lang1, this.ui.btnBottom, e);
        });

        window.addEventListener('pointerup', (e) => this.stopRecording(e));
        window.addEventListener('pointercancel', (e) => this.stopRecording(e));
    }

    updateUIPair() {
        const [lang1, lang2] = this.ui.pairSelector.value.split('-');
        const l1 = this.langConfig[lang1];
        const l2 = this.langConfig[lang2];

        this.ui.btnTopLabel.innerText = `${l1.flag} ${l1.name} ➔ ${l2.name}`;
        this.ui.btnTop.style.setProperty('--current-color', l1.color);

        this.ui.btnBottomLabel.innerText = `${l2.flag} ${l2.name} ➔ ${l1.name}`;
        this.ui.btnBottom.style.setProperty('--current-color', l2.color);
    }

    async initMicrophone() {
        try {
            const constraints = {
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false,
                    sampleRate: 48000,
                    channelCount: 1
                }
            };
            this.audioStream = await navigator.mediaDevices.getUserMedia(constraints);
        } catch (err) {
            this.updateStatus("Ошибка доступа к микрофону!");
            console.error("Microphone access failed:", err);
        }
    }

    // Пробуждаем аудио-ядро при нажатии (iOS/Android требуют этого для Web Audio API)
    unlockAudioPlayer() {
        if (this.audioCtx.state === 'suspended') {
            this.audioCtx.resume();
        }
    }

    async startRecording(sourceLang, targetLang, activeBtn, event) {
        if (event && !event.isPrimary) return;
        event.preventDefault();

        this.unlockAudioPlayer(); // Будим динамик

        if (this.state.isRecording) return;

        // Если сокет от прошлого раза завис - убиваем
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.close();
        }

        if (!this.audioStream || !this.audioStream.active) {
            this.updateStatus("Будим микрофон...");
            await this.initMicrophone();
            if (!this.audioStream) return;
        }

        this.state.currentSource = sourceLang;
        this.state.currentTarget = targetLang;
        this.state.isRecording = true;
        this.state.ignoreRecording = false;
        this.state.recordStartTime = Date.now();

        this.ui.dotSource.style.color = this.langConfig[sourceLang].color;
        this.ui.dotTarget.style.color = this.langConfig[targetLang].color;
        this.ui.recognized.innerText = '...';
        this.ui.translated.innerText = '...';

        activeBtn.classList.add('recording');
        this.updateStatus("Подключение к серверу...");

        // === WEBSOCKET СТРИМИНГ ===
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/api/web/ws/translate`);

        // Как только тоннель открыт:
        this.ws.onopen = () => {
            this.updateStatus("Слушаю... Отпустите для перевода");

            // 1. Отправляем JSON с настройками
            this.ws.send(JSON.stringify({
                source_lang: sourceLang,
                target_lang: targetLang
            }));

            // 2. Включаем микрофон в режиме стриминга (по 250 мс)
            this.setupMediaRecorder();
            this.mediaRecorder.start(250);
        };

        // Когда сервер присылает данные обратно:
        this.ws.onmessage = async (e) => {
            // Если прилетел Текст (JSON от LLM или STT)
            if (typeof e.data === 'string') {
                const data = JSON.parse(e.data);
                if (data.type === 'stt') {
                    this.ui.recognized.innerText = data.text;
                    this.updateStatus("Перевод...");
                } else if (data.type === 'llm') {
                    this.ui.translated.innerText = data.text;
                    this.updateStatus("Озвучиваю...");
                } else if (data.type === 'audio_done') {
                    this.updateStatus("Готово!");
                    this.ws.close(); // Все получили, можно закрывать сокет
                }
            }
            // Если прилетел Звук (Бинарные данные MP3)
            else if (e.data instanceof Blob) {
                try {
                    const arrayBuffer = await e.data.arrayBuffer();
                    const audioBuffer = await this.audioCtx.decodeAudioData(arrayBuffer);
                    const source = this.audioCtx.createBufferSource();
                    source.buffer = audioBuffer;
                    source.connect(this.audioCtx.destination);
                    source.start(0); // Проигрываем МГНОВЕННО без плеера
                } catch (err) {
                    console.error("Ошибка Web Audio API:", err);
                }
            }
        };

        this.ws.onerror = (e) => {
            console.error("WS Error:", e);
            this.updateStatus("Ошибка соединения");
        };
    }

    setupMediaRecorder() {
        let options = { audioBitsPerSecond: 128000 };
        if (MediaRecorder.isTypeSupported('audio/webm')) {
            options.mimeType = 'audio/webm';
        } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
            options.mimeType = 'audio/mp4';
        }

        this.mediaRecorder = new MediaRecorder(this.audioStream, options);

        // Магия стриминга: льем звук в сокет по мере появления
        this.mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(e.data);
            }
        };
    }

    stopRecording(event) {
        if (!this.state.isRecording || !this.mediaRecorder) return;
        event.preventDefault();

        const duration = Date.now() - this.state.recordStartTime;

        // Если случайно кликнули (меньше 0.5 сек)
        if (duration < 500) {
            this.state.ignoreRecording = true;
            this.updateStatus("Слишком короткое нажатие");
            if (this.ws) this.ws.close();

            setTimeout(() => {
                if (!this.state.isRecording) this.updateStatus("Зажмите кнопку для перевода");
            }, 1500);
        } else {
            this.updateStatus("Распознавание Deepgram...");
        }

        // Останавливаем запись (сокет не закрываем, ждем ответ от сервера!)
        if (this.mediaRecorder.state === 'recording') {
            this.mediaRecorder.stop();
        }

        this.ui.btnTop.classList.remove('recording');
        this.ui.btnBottom.classList.remove('recording');
        this.state.isRecording = false;
    }

    updateStatus(message) {
        this.ui.status.innerText = message;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.app = new VoiceTranslator();
});