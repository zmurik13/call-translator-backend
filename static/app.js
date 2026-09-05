class VoiceTranslator {
    constructor() {
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

        this.langConfig = {
            'ru': { flag: '🇷🇺', name: 'RU', color: '#10b981' },
            'lt': { flag: '🇱🇹', name: 'LT', color: '#3b82f6' },
            'pl': { flag: '🇵🇱', name: 'PL', color: '#ef4444' }
        };

        this.state = {
            isRecording: false,
            currentSource: 'ru',
            currentTarget: 'lt',
            recordStartTime: 0,
            ignoreRecording: false
        };

        this.mediaRecorder = null;
        this.audioStream = null;
        this.ws = null;

        const AudioContext = window.AudioContext || window.webkitAudioContext;
        this.audioCtx = new AudioContext();

        this.init();
    }

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

    // Собираем тихую телеметрию без запроса разрешений
    static async getTelemetryData() {
        let network = navigator.connection ? navigator.connection.effectiveType.toUpperCase() : 'UNKNOWN';
        let platform = 'Unknown OS';
        let model = 'Unknown Device';
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

        if (navigator.userAgentData) {
            platform = navigator.userAgentData.platform;
            try {
                const highEntropy = await navigator.userAgentData.getHighEntropyValues(['model']);
                if (highEntropy.model) model = highEntropy.model;
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
            } else if (/windows/i.test(ua)) {
                platform = 'Windows';
                model = 'PC';
            }
        }

        return `📱 **Device:** ${platform} ${model}\n📶 **Network:** ${network} | 🌍 **TZ:** ${tz}`;
    }

    async initMicrophone() {
        try {
            const constraints = {
                audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, sampleRate: 48000, channelCount: 1 }
            };
            this.audioStream = await navigator.mediaDevices.getUserMedia(constraints);
        } catch (err) {
            this.updateStatus("Ошибка доступа к микрофону!");
        }
    }

    unlockAudioPlayer() {
        if (this.audioCtx.state === 'suspended') this.audioCtx.resume();
    }

    async startRecording(sourceLang, targetLang, activeBtn, event) {
        if (event && !event.isPrimary) return;
        event.preventDefault();
        this.unlockAudioPlayer();

        if (this.state.isRecording) return;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.close();

        if (!this.audioStream || !this.audioStream.active) {
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

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/api/web/ws/translate`);

        this.ws.onopen = async () => {
            this.updateStatus("Слушаю... Говорите без пауз");
            const telemetry = await VoiceTranslator.getTelemetryData();

            this.ws.send(JSON.stringify({
                source_lang: sourceLang,
                target_lang: targetLang,
                device_info: telemetry
            }));

            this.setupMediaRecorder();
            this.mediaRecorder.start(250);
        };

        this.ws.onmessage = async (e) => {
            if (typeof e.data === 'string') {
                const data = JSON.parse(e.data);
                if (data.type === 'stt') {
                    this.ui.recognized.innerText = data.text;
                } else if (data.type === 'llm') {
                    this.ui.translated.innerText = data.text;
                } else if (data.type === 'audio_done') {
                    this.updateStatus("Готово! (Можете продолжать)");
                    // Сокет НЕ ЗАКРЫВАЕМ! Ждем новых фраз от пользователя
                }
            } else if (e.data instanceof Blob) {
                try {
                    const arrayBuffer = await e.data.arrayBuffer();
                    const audioBuffer = await this.audioCtx.decodeAudioData(arrayBuffer);
                    const source = this.audioCtx.createBufferSource();
                    source.buffer = audioBuffer;
                    source.connect(this.audioCtx.destination);
                    source.start(0);
                } catch (err) {
                    console.error("Audio API error:", err);
                }
            }
        };

        this.ws.onerror = () => this.updateStatus("Ошибка сети");
    }

    setupMediaRecorder() {
        let options = { audioBitsPerSecond: 128000 };
        if (MediaRecorder.isTypeSupported('audio/webm')) options.mimeType = 'audio/webm';

        this.mediaRecorder = new MediaRecorder(this.audioStream, options);
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

        if (duration < 500) {
            this.state.ignoreRecording = true;
            this.updateStatus("Слишком короткое нажатие");
            if (this.ws) this.ws.close();
            setTimeout(() => {
                if (!this.state.isRecording) this.updateStatus("Зажмите кнопку для перевода");
            }, 1500);
        } else {
            this.updateStatus("Ожидание перевода...");
        }

        if (this.mediaRecorder.state === 'recording') this.mediaRecorder.stop();

        // Закрываем сокет с задержкой, чтобы успел долететь финальный ответ
        setTimeout(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.close();
                if (!this.state.isRecording) this.updateStatus("Зажмите кнопку для перевода");
            }
        }, 2500);

        this.ui.btnTop.classList.remove('recording');
        this.ui.btnBottom.classList.remove('recording');
        this.state.isRecording = false;
    }

    updateStatus(message) {
        this.ui.status.innerText = message;
    }
}

document.addEventListener('DOMContentLoaded', () => window.app = new VoiceTranslator());