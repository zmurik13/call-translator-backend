class VoiceTranslator {
    constructor() {
        // UI Elements
        this.ui = {
            status: document.getElementById('status'),
            recognized: document.getElementById('recognized'),
            translated: document.getElementById('translated'),
            btnRu: document.getElementById('btnRu'),
            btnLt: document.getElementById('btnLt')
        };

        // Application State
        this.state = {
            isRecording: false,
            isPlayerUnlocked: false,
            currentLang: 'ru',
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
        this.initMicrophone();
    }

    // Bind UI events using modern Pointer API
    bindEvents() {
        // Prevent default context menu on long press (especially for mobile devices)
        [this.ui.btnRu, this.ui.btnLt].forEach(btn => {
            btn.addEventListener('contextmenu', e => e.preventDefault());
        });

        // Pointerdown replaces both mousedown and touchstart
        this.ui.btnRu.addEventListener('pointerdown', (e) => this.startRecording('ru', e));
        this.ui.btnLt.addEventListener('pointerdown', (e) => this.startRecording('lt', e));

        // Listen for pointerup and pointercancel globally so we don't get stuck
        // if the user drags their finger off the button before releasing
        window.addEventListener('pointerup', (e) => this.stopRecording(e));
        window.addEventListener('pointercancel', (e) => this.stopRecording(e));
    }

    // Get device telemetry (static because it doesn't depend on class state)
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

    // Request microphone access without audio processing filters
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
        this.globalPlayer.play().catch(err => console.log("Audio unlock failed (likely normal behavior)", err));
        this.state.isPlayerUnlocked = true;
    }

    // Start recording process
    async startRecording(lang, event) {
        // Ignore multi-touch or secondary mouse buttons
        if (event && !event.isPrimary) return;

        event.preventDefault();
        this.unlockAudioPlayer();

        if (this.state.isRecording) return;

        // Wake up microphone if track ended (e.g., background sleep on mobile)
        if (!this.audioStream || !this.audioStream.active || this.audioStream.getAudioTracks()[0].readyState === 'ended') {
            this.updateStatus("Будим микрофон...");
            await this.initMicrophone();
            if (!this.audioStream) return;
        }

        this.state.currentLang = lang;
        this.state.isRecording = true;
        this.state.ignoreRecording = false;
        this.state.recordStartTime = Date.now();
        this.audioChunks = [];

        this.setupMediaRecorder();
        this.mediaRecorder.start();

        // UI Updates
        this.ui.btnRu.classList.remove('recording');
        this.ui.btnLt.classList.remove('recording');
        const activeBtn = lang === 'ru' ? this.ui.btnRu : this.ui.btnLt;
        activeBtn.classList.add('recording');

        this.updateStatus("Слушаю... Отпустите для перевода");
    }

    // Configure MediaRecorder and handle data flow
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

        // Prevent accidental clicks
        if (duration < 500) {
            this.state.ignoreRecording = true;
            this.updateStatus("Слишком короткое нажатие");
            setTimeout(() => {
                if (!this.state.isRecording) this.updateStatus("Зажмите кнопку нужного языка");
            }, 1500);
        }

        if (this.mediaRecorder.state === 'recording') {
            this.mediaRecorder.stop();
        }

        this.ui.btnRu.classList.remove('recording');
        this.ui.btnLt.classList.remove('recording');
        this.state.isRecording = false;
    }

    // Send audio to backend and handle response
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
        formData.append('source_lang', this.state.currentLang);

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

    // Helper to centralize status updates
    updateStatus(message) {
        this.ui.status.innerText = message;
    }
}

// Initialize application when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new VoiceTranslator();
});