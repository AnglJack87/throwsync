// ThrowSync Overlay Injector v1.6.0
// Injected via bookmarklet into any page (Autodarts, Darthelfer, etc.)
// Connects to ThrowSync WebSocket and shows HUD + Clips + Toasts

(function() {
    'use strict';

    // Prevent double injection
    if (window.__throwsync_injected) {
        console.log('ThrowSync: Already injected, toggling visibility');
        const el = document.getElementById('throwsync-overlay');
        if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
        return;
    }
    window.__throwsync_injected = true;

    // ── Config ──
    const TS_HOST = '__THROWSYNC_HOST__'; // replaced by backend
    const WS_URL = 'ws://' + TS_HOST + '/ws';

    // ── State ──
    const state = {
        connected: false,
        score: null,
        remaining: null,
        lastThrow: null,
        hudVisible: true,
    };

    // ── Create overlay container ──
    const overlay = document.createElement('div');
    overlay.id = 'throwsync-overlay';
    overlay.innerHTML = '';
    document.body.appendChild(overlay);

    // ── Styles ──
    const style = document.createElement('style');
    style.textContent = `
        #throwsync-overlay { position: fixed; inset: 0; pointer-events: none; z-index: 2147483647; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
        #throwsync-overlay * { box-sizing: border-box; }

        /* HUD Bar */
        #ts-hud {
            position: fixed; bottom: 0; left: 0; right: 0;
            display: flex; align-items: center; justify-content: center; gap: 20px;
            padding: 6px 16px; height: 44px;
            background: rgba(0, 0, 0, 0.8);
            backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
            border-top: 1px solid rgba(255,255,255,0.1);
            pointer-events: auto;
            transition: transform 0.3s ease, opacity 0.3s ease;
            user-select: none;
        }
        #ts-hud.hidden { transform: translateY(100%); opacity: 0; }

        .ts-hud-item { display: flex; align-items: center; gap: 6px; color: #fff; }
        .ts-hud-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: rgba(255,255,255,0.4); }
        .ts-hud-val { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .ts-hud-val.score { color: #8b5cf6; }
        .ts-hud-val.rest { color: #10b981; }
        .ts-hud-val.throw { color: #f59e0b; }
        .ts-hud-div { width: 1px; height: 24px; background: rgba(255,255,255,0.15); }

        /* Connection dot */
        .ts-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
        .ts-dot.on { background: #10b981; box-shadow: 0 0 6px #10b981; }
        .ts-dot.off { background: #ef4444; box-shadow: 0 0 6px #ef4444; }

        /* Toggle button */
        #ts-toggle {
            position: fixed; bottom: 8px; right: 8px;
            width: 28px; height: 28px; border-radius: 50%;
            background: rgba(139, 92, 246, 0.9); color: #fff;
            border: none; cursor: pointer; font-size: 14px;
            pointer-events: auto; z-index: 2147483647;
            display: flex; align-items: center; justify-content: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            transition: opacity 0.2s;
        }
        #ts-toggle:hover { opacity: 0.8; }
        #ts-hud:not(.hidden) ~ #ts-toggle { bottom: 52px; }

        /* Toast */
        #ts-toast {
            position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
            padding: 8px 24px; border-radius: 24px;
            background: rgba(0, 0, 0, 0.85);
            backdrop-filter: blur(8px);
            color: #fff; font-size: 20px; font-weight: 700;
            border: 1px solid rgba(255,255,255,0.15);
            pointer-events: none;
            opacity: 0; transition: opacity 0.3s ease;
            white-space: nowrap;
        }
        #ts-toast.show { opacity: 1; }

        /* Clip overlay */
        #ts-clip {
            position: fixed; inset: 0;
            display: flex; align-items: center; justify-content: center;
            background: rgba(0, 0, 0, 0.75);
            pointer-events: none;
            opacity: 0; transition: opacity 0.3s ease;
        }
        #ts-clip.show { opacity: 1; pointer-events: auto; cursor: pointer; }
        #ts-clip.show video, #ts-clip.show img {
            max-width: 80vw; max-height: 80vh;
            border-radius: 16px;
            box-shadow: 0 0 60px rgba(139, 92, 246, 0.4);
        }

        /* LED strip */
        #ts-led {
            position: fixed; bottom: 44px; left: 0; right: 0;
            height: 3px; pointer-events: none;
            transition: background 0.5s ease;
        }

        /* Branding */
        .ts-brand {
            font-size: 9px; color: rgba(255,255,255,0.25);
            letter-spacing: 1px; font-weight: 600;
        }

        @keyframes ts-fadeIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
    `;
    document.head.appendChild(style);

    // ── Build HUD ──
    function render() {
        overlay.innerHTML = `
            <div id="ts-led"></div>
            <div id="ts-hud" class="${state.hudVisible ? '' : 'hidden'}">
                <span class="ts-brand">THROWSYNC</span>
                <span class="ts-dot ${state.connected ? 'on' : 'off'}"></span>
                <div class="ts-hud-div"></div>
                <div class="ts-hud-item">
                    <div>
                        <div class="ts-hud-label">Aufnahme</div>
                        <div class="ts-hud-val score">${state.score !== null ? state.score : '\u2014'}</div>
                    </div>
                </div>
                <div class="ts-hud-div"></div>
                <div class="ts-hud-item">
                    <div>
                        <div class="ts-hud-label">Rest</div>
                        <div class="ts-hud-val rest">${state.remaining !== null ? state.remaining : '\u2014'}</div>
                    </div>
                </div>
                <div class="ts-hud-div"></div>
                <div class="ts-hud-item">
                    <div>
                        <div class="ts-hud-label">Letzter Wurf</div>
                        <div class="ts-hud-val throw">${state.lastThrow || '\u2014'}</div>
                    </div>
                </div>
            </div>
            <div id="ts-toast"></div>
            <div id="ts-clip" onclick="this.className='';this.innerHTML='';"></div>
            <button id="ts-toggle" onclick="document.getElementById('ts-hud').classList.toggle('hidden')" title="ThrowSync HUD">&#x25C6;</button>
        `;
    }

    // ── Toast ──
    let toastTimer = null;
    function showToast(text) {
        const el = document.getElementById('ts-toast');
        if (!el) return;
        el.textContent = text;
        el.className = 'show';
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.className = ''; }, 3500);
    }

    // ── Clip ──
    let clipTimer = null;
    function showClip(url, duration) {
        const el = document.getElementById('ts-clip');
        if (!el) return;
        clearTimeout(clipTimer);
        const fullUrl = url.startsWith('http') ? url : 'http://' + TS_HOST + '/clips/' + url;
        const isVideo = fullUrl.match(/\.(mp4|webm|mov)$/i);
        el.innerHTML = isVideo
            ? '<video src="' + fullUrl + '" autoplay style="max-width:80vw;max-height:80vh;border-radius:16px;box-shadow:0 0 60px rgba(139,92,246,0.4)"></video>'
            : '<img src="' + fullUrl + '" style="max-width:80vw;max-height:80vh;border-radius:16px;box-shadow:0 0 60px rgba(139,92,246,0.4)">';
        el.className = 'show';
        clipTimer = setTimeout(() => { el.className = ''; el.innerHTML = ''; }, duration * 1000);
    }

    // ── Audio ──
    const audioCache = {};
    let audioQueue = [];
    let audioPlaying = false;
    let currentAudio = null;

    async function playAudio(sounds, globalVol, priority) {
        if (priority >= 1 && audioPlaying) {
            audioQueue = [];
            if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; currentAudio = null; }
            audioPlaying = false;
        }
        if (audioQueue.length > 3) audioQueue = audioQueue.slice(-2);

        sounds.sort((a, b) => (a.priority || 1) - (b.priority || 1)).forEach(s => {
            if (s.sound) {
                const url = s.sound.startsWith('http') ? s.sound : 'http://' + TS_HOST + '/sounds/' + s.sound;
                audioQueue.push({ url, vol: s.volume || 1.0, globalVol });
            }
        });

        if (audioPlaying) return;
        audioPlaying = true;
        while (audioQueue.length > 0) {
            const item = audioQueue.shift();
            try {
                let audio = audioCache[item.url];
                if (!audio) { audio = new Audio(item.url); audioCache[item.url] = audio; }
                audio.volume = Math.min(1, Math.max(0, (item.globalVol || 0.8) * (item.vol || 1.0)));
                audio.currentTime = 0;
                currentAudio = audio;
                await new Promise(resolve => {
                    const t = setTimeout(() => { audio.pause(); audio.currentTime = 0; resolve(); }, 4000);
                    audio.onended = () => { clearTimeout(t); resolve(); };
                    audio.onerror = () => { clearTimeout(t); resolve(); };
                    audio.play().catch(() => { clearTimeout(t); resolve(); });
                });
                currentAudio = null;
            } catch(e) {}
        }
        audioPlaying = false;
    }

    // ── WebSocket ──
    let ws = null;
    function connectWS() {
        try { ws = new WebSocket(WS_URL); } catch(e) { setTimeout(connectWS, 3000); return; }

        ws.onopen = () => { state.connected = true; render(); console.log('ThrowSync: Connected'); };
        ws.onclose = () => { state.connected = false; render(); setTimeout(connectWS, 2000); };
        ws.onerror = () => { try { ws.close(); } catch(e) {} };

        ws.onmessage = (e) => {
            let msg;
            try { msg = JSON.parse(e.data); } catch(err) { return; }

            // Caller sounds
            if (msg.type === 'caller_play' && msg.sounds) {
                playAudio(msg.sounds, msg.volume || 0.8, msg.priority || 0);
            }

            // Clips
            if (msg.type === 'caller_clip' && msg.clip) {
                showClip(msg.clip, msg.clip_duration || 5);
            }

            // Crowd sounds (separate channel, concurrent with caller)
            if (msg.type === 'crowd_play' && msg.sounds) {
                const gv = msg.volume || 0.5;
                msg.sounds.forEach(s => {
                    if (s.sound) {
                        const url = s.sound.startsWith('http') ? s.sound : 'http://' + TS_HOST + '/sounds/' + s.sound;
                        const a = new Audio(url);
                        a.volume = Math.min(1, Math.max(0, gv * (s.volume || 0.5)));
                        a.play().catch(() => {});
                    }
                });
            }

            // Display state (score, remaining, throws)
            if (msg.type === 'display_state') {
                const d = msg.data || {};
                if (d.type === 'throw') {
                    state.lastThrow = d.throw_text || '?';
                    state.score = d.turn_score || 0;
                    render();
                }
                if (d.type === 'state_update') {
                    if (d.remaining !== undefined) state.remaining = d.remaining;
                    render();
                }
            }

            // Event toasts
            if (msg.type === 'event_fired') {
                const ev = (msg.entry || {}).event;
                const toasts = {
                    '180': '\uD83D\uDD25 180!',
                    'bullseye': '\uD83C\uDFAF BULLSEYE!',
                    'match_won': '\uD83C\uDFC6 MATCH GEWONNEN!',
                    'game_won': '\uD83C\uDF89 LEG GEWONNEN!',
                    'busted': '\uD83D\uDCA5 BUST!',
                    'miss': '\uD83D\uDE05 Daneben!',
                };
                if (toasts[ev]) showToast(toasts[ev]);
                if (ev === 'game_on' || ev === 'game_won' || ev === 'match_won') {
                    state.score = 0;
                    render();
                }
            }
        };
    }

    // ── Init ──
    render();
    connectWS();
    console.log('ThrowSync: Overlay injected, connecting to ' + TS_HOST);
})();
