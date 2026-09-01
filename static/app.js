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
            isPlayerUnlocked: false,
            currentSource: 'ru',
            currentTarget: 'lt',
            recordStartTime: 0,
            ignoreRecording: false
        };

        // Media & Audio
        this.mediaRecorder = null;
        this.audioStream = null;
        this.audioChunks = [];
        this.globalPlayer = new Audio();

        this.init();
    }

    // Initialize application
    init() {
        this.bindEvents();
        this.updateUIPair();
        this.initMicrophone();
    }

    // Bind UI events using modern Pointer API
    bindEvents() {
        // Слушаем изменение в выпадающем списке
        this.ui.pairSelector.addEventListener('change', () => this.updateUIPair());

        // Prevent default context menu on long press
        [this.ui.btnTop, this.ui.btnBottom].forEach(btn => {
            btn.addEventListener('contextmenu', e => e.preventDefault());
        });

        // Кнопка 1 (Сверху вниз)
        this.ui.btnTop.addEventListener('pointerdown', (e) => {
            const [lang1, lang2] = this.ui.pairSelector.value.split('-');
            this.startRecording(lang1, lang2, this.ui.btnTop, e);
        });

        // Кнопка 2 (Снизу вверх)
        this.ui.btnBottom.addEventListener('pointerdown', (e) => {
            const [lang1, lang2] = this.ui.pairSelector.value.split('-');
            this.startRecording(lang2, lang1, this.ui.btnBottom, e);
        });

        // Listen for pointerup globally
        window.addEventListener('pointerup', (e) => this.stopRecording(e));
        window.addEventListener('pointercancel', (e) => this.stopRecording(e));
    }

    // Обновляем текст и цвета кнопок при смене пары языков
    updateUIPair() {
        const [lang1, lang2] = this.ui.pairSelector.value.split('-');
        const l1 = this.langConfig[lang1];
        const l2 = this.langConfig[lang2];

        this.ui.btnTopLabel.innerText = `${l1.flag} ${l1.name} ➔ ${l2.name}`;
        this.ui.btnTop.style.setProperty('--current-color', l1.color);

        this.ui.btnBottomLabel.innerText = `${l2.flag} ${l2.name} ➔ ${l1.name}`;
        this.ui.btnBottom.style.setProperty('--current-color', l2.color);
    }

    // Get FULL device telemetry (Оригинальная версия)
    static async getTelemetryData() {
        let network = navigator.connection ? navigator.connection.effectiveType.toUpperCase() : 'UNKNOWN';
        let platform = 'Unknown OS';
        let model = 'Unknown Device';

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

        if (model === 'Unknown Device') {
            const ua = navigator.userAgent;
            if (/android/i.test(ua)) {
                platform = 'Android';
                const match = ua.match(/Android\s+[0-9\.]+;\s+([^;)]+)/);
                if (match && match[1]) model = match[1].trim();
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

        return `📱 Model: ${platform} ${model}\n📶 Network: ${network}`;
    }

    // Request microphone access
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

    // Unlock audio context for iOS
    unlockAudioPlayer() {
        if (this.state.isPlayerUnlocked) return;
        this.globalPlayer.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
        this.globalPlayer.play().catch(err => console.log("Audio unlock failed", err));
        this.state.isPlayerUnlocked = true;
    }

    // Start recording process
    async startRecording(sourceLang, targetLang, activeBtn, event) {
        if (event && !event.isPrimary) return;
        event.preventDefault();
        this.unlockAudioPlayer();

        if (this.state.isRecording) return;

        // Wake up microphone if needed
        if (!this.audioStream || !this.audioStream.active || this.audioStream.getAudioTracks()[0].readyState === 'ended') {
            this.updateStatus("Будим микрофон...");
            await this.initMicrophone();
            if (!this.audioStream) return;
        }

        this.state.currentSource = sourceLang;
        this.state.currentTarget = targetLang;
        this.state.isRecording = true;
        this.state.ignoreRecording = false;
        this.state.recordStartTime = Date.now();
        this.audioChunks = [];

        // Устанавливаем цвета точек у текста
        this.ui.dotSource.style.color = this.langConfig[sourceLang].color;
        this.ui.dotTarget.style.color = this.langConfig[targetLang].color;

        this.setupMediaRecorder();
        this.mediaRecorder.start();

        activeBtn.classList.add('recording');
        this.updateStatus("Слушаю... Отпустите для перевода");
    }

    // Configure MediaRecorder
    setupMediaRecorder() {
        let options = { audioBitsPerSecond: 128000 };
        let ext = 'webm';

        if (MediaRecorder.isTypeSupported('audio/webm')) {
            options.mimeType = 'audio/webm';
        } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
            options.mimeType = 'audio/mp4';
            ext = 'mp4';
        }

        this.mediaRecorder = new MediaRecorder(this.audioStream, options);

        this.mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) this.audioChunks.push(e.data);
        };

        this.mediaRecorder.onstop = async () => this.processAudio(ext, options);
    }

    // Stop recording process
    stopRecording(event) {
        if (!this.state.isRecording || !this.mediaRecorder) return;
        event.preventDefault();

        const duration = Date.now() - this.state.recordStartTime;

        if (duration < 500) {
            this.state.ignoreRecording = true;
            this.updateStatus("Слишком короткое нажатие");
            setTimeout(() => {
                if (!this.state.isRecording) this.updateStatus("Зажмите кнопку для перевода");
            }, 1500);
        }

        if (this.mediaRecorder.state === 'recording') {
            this.mediaRecorder.stop();
        }

        this.ui.btnTop.classList.remove('recording');
        this.ui.btnBottom.classList.remove('recording');
        this.state.isRecording = false;
    }

    // Send audio to backend
    async processAudio(ext, options) {
        if (this.state.ignoreRecording) {
            this.audioChunks = [];
            return;
        }

        this.updateStatus("Обработка (Groq + TTS)...");
        const audioBlob = new Blob(this.audioChunks, options);
        this.audioChunks = [];

        const formData = new FormData();
        formData.append('audio', audioBlob, `record.${ext}`);
        formData.append('source_lang', this.state.currentSource);
        formData.append('target_lang', this.state.currentTarget); // Отправляем целевой язык

        const telemetry = await VoiceTranslator.getTelemetryData();
        formData.append('device_info', telemetry);

        try {
            const response = await fetch('/api/web/translate-voice', { method: 'POST', body: formData });
            if (!response.ok) throw new Error(await response.text());

            this.ui.recognized.innerText = JSON.parse(`"${response.headers.get("X-Recognized-Text") || ""}"`);
            this.ui.translated.innerText = JSON.parse(`"${response.headers.get("X-Translated-Text") || ""}"`);

            const audioUrl = URL.createObjectURL(await response.blob());
            this.globalPlayer.src = audioUrl;
            this.globalPlayer.play();

            this.updateStatus("Готово!");
        } catch (err) {
            this.updateStatus("Ошибка обработки");
            console.error("API request failed:", err);
        }
    }

    updateStatus(message) {
        this.ui.status.innerText = message;
    }
}

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    window.app = new VoiceTranslator();
});