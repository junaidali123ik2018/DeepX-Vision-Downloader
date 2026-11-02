// DeepX Vision Downloader - IDM Video Assistant Content Script
(function () {
    if (window.__deepx_content_injected) return;
    window.__deepx_content_injected = true;

    const CANDIDATE_PORTS = [18932, 18933, 18934, 18935];

    // 1. YouTube Player Metadata Sniffer (adapted from Awesome Downloader)
    if (window.location.hostname.includes('youtube.com')) {
        const interceptScript = document.createElement('script');
        interceptScript.textContent = `
            (() => {
                window.__deepx_yt_formats = [];
                function parsePlayer(data) {
                    try {
                        const formats = data?.streamingData?.formats || [];
                        const adaptive = data?.streamingData?.adaptiveFormats || [];
                        const all = [...formats, ...adaptive];
                        const list = [];
                        for (const f of all) {
                            if (f.qualityLabel && !list.some(x => x.quality === f.qualityLabel)) {
                                list.push({
                                    quality: f.qualityLabel,
                                    fps: f.fps || 30,
                                    size: f.contentLength ? (parseInt(f.contentLength) / (1024*1024)).toFixed(1) + ' MB' : null
                                });
                            }
                        }
                        if (list.length > 0) {
                            window.__deepx_yt_formats = list;
                            window.dispatchEvent(new CustomEvent('deepx_yt_formats_ready', { detail: list }));
                        }
                    } catch(e) {}
                }

                const origFetch = window.fetch;
                window.fetch = function(...args) {
                    const result = Reflect.apply(origFetch, this, args);
                    const url = args[0]?.url || args[0];
                    if (typeof url === 'string' && url.includes('/youtubei/v1/player')) {
                        result.then(res => res.clone().json()).then(data => parsePlayer(data)).catch(() => {});
                    }
                    return result;
                };

                const origOpen = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                    if (typeof url === 'string' && url.includes('/youtubei/v1/player')) {
                        this.addEventListener('load', () => {
                            try { parsePlayer(JSON.parse(this.responseText)); } catch(e) {}
                        }, { once: true });
                    }
                    return Reflect.apply(origOpen, this, [method, url, ...rest]);
                };

                if (window.ytInitialPlayerResponse) parsePlayer(window.ytInitialPlayerResponse);
            })();
        `;
        (document.head || document.documentElement).appendChild(interceptScript);
        interceptScript.remove();
    }

    // 2. Queue Download IPC
    function queueDownload(url, mediaType = 'video', quality = 'Best Available') {
        const targetUrl = url || window.location.href;
        console.log('[DeepX Extension] Queuing download:', targetUrl, mediaType, quality);

        // A. Send to Extension background service worker
        try {
            if (chrome && chrome.runtime && chrome.runtime.sendMessage) {
                chrome.runtime.sendMessage({
                    action: 'download',
                    url: targetUrl,
                    title: document.title,
                    media_type: mediaType,
                    quality: quality
                });
            }
        } catch (e) {}

        // B. Direct Local HTTP IPC fallback
        for (const port of CANDIDATE_PORTS) {
            try {
                fetch(`http://127.0.0.1:${port}/download`, {
                    method: 'POST',
                    mode: 'cors',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: targetUrl,
                        title: document.title,
                        media_type: mediaType,
                        quality: quality,
                        browser: 'DeepX Video Extension'
                    })
                }).catch(() => {});
            } catch (e) {}
        }

        // C. Fast clipboard copy fallback
        try {
            const ta = document.createElement('textarea');
            ta.value = targetUrl;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            (document.body || document.documentElement).appendChild(ta);
            ta.focus();
            ta.select();
            document.execCommand('copy');
            ta.remove();
        } catch (e) {}
    }

    // 3. Shadow DOM Isolated Floating Video Download Bar
    function createIdmBar(getUrlFn, getTitleFn) {
        const host = document.createElement('div');
        host.className = 'deepx-idm-host';
        host.style.cssText = 'position: absolute !important; top: 12px !important; right: 12px !important; z-index: 2147483647 !important; display: inline-block !important; pointer-events: auto !important;';

        const shadow = host.attachShadow({ mode: 'open' });
        shadow.innerHTML = `
            <style>
                :host {
                    all: initial;
                    font-family: "Segoe UI", Tahoma, sans-serif;
                }
                .bar-container {
                    display: inline-flex;
                    align-items: center;
                    position: relative;
                    font-family: "Segoe UI", Tahoma, sans-serif;
                    user-select: none;
                    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.75);
                    border-radius: 6px;
                    border: 1px solid rgba(56, 189, 248, 0.5);
                    background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
                    cursor: pointer;
                    height: 32px;
                    line-height: 1;
                    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
                }
                .bar-container:hover {
                    transform: scale(1.03);
                    border-color: #38BDF8;
                    box-shadow: 0 6px 24px rgba(37, 99, 235, 0.65);
                }
                .main-btn {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 0 10px;
                    height: 100%;
                    color: #FFFFFF;
                    font-size: 12px;
                    font-weight: 700;
                    border-right: 1px solid rgba(255, 255, 255, 0.15);
                    transition: background 0.15s ease;
                }
                .main-btn:hover {
                    background: rgba(37, 99, 235, 0.35);
                }
                .arrow-btn {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 26px;
                    height: 100%;
                    color: #38BDF8;
                    font-size: 10px;
                    transition: background 0.15s ease, color 0.15s ease;
                }
                .arrow-btn:hover {
                    background: rgba(37, 99, 235, 0.35);
                    color: #FFFFFF;
                }
                .dropdown {
                    display: none;
                    position: absolute;
                    top: 36px;
                    right: 0;
                    min-width: 200px;
                    background: #0F172A;
                    border: 1px solid rgba(56, 189, 248, 0.4);
                    border-radius: 8px;
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.85);
                    overflow: hidden;
                    z-index: 2147483647;
                }
                .dropdown.show {
                    display: block;
                }
                .menu-item {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 12px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #E2E8F0;
                    cursor: pointer;
                    transition: background 0.15s ease, color 0.15s ease;
                }
                .menu-item:hover {
                    background: #2563EB;
                    color: #FFFFFF;
                }
                .menu-item span.size-badge {
                    margin-left: auto;
                    font-size: 10px;
                    color: #94A3B8;
                    background: rgba(255, 255, 255, 0.08);
                    padding: 2px 5px;
                    border-radius: 4px;
                }
            </style>
            <div class="bar-container">
                <div class="main-btn">
                    <span>⚡</span> <span>Download this video</span>
                </div>
                <div class="arrow-btn">▼</div>
                <div class="dropdown">
                    <div class="menu-item item-video" data-type="video">
                        <span>🎬</span> <span>Best Quality (1080p / 4K)</span>
                    </div>
                    <div class="menu-item item-audio" data-type="audio">
                        <span>🎵</span> <span>Download Audio (MP3)</span>
                    </div>
                    <div class="menu-item item-open">
                        <span>⚡</span> <span>Open in DeepX App</span>
                    </div>
                </div>
            </div>
        `;

        const container = shadow.querySelector('.bar-container');
        const mainBtn = shadow.querySelector('.main-btn');
        const arrowBtn = shadow.querySelector('.arrow-btn');
        const dropdown = shadow.querySelector('.dropdown');
        const itemVideo = shadow.querySelector('.item-video');
        const itemAudio = shadow.querySelector('.item-audio');
        const itemOpen = shadow.querySelector('.item-open');

        function triggerDownload(type, quality = 'Best Available') {
            const u = (typeof getUrlFn === 'function' ? getUrlFn() : getUrlFn) || window.location.href;
            mainBtn.innerHTML = '<span>✓</span> <span>Queued!</span>';
            container.style.borderColor = '#10B981';
            queueDownload(u, type, quality);
            setTimeout(() => {
                mainBtn.innerHTML = '<span>⚡</span> <span>Download this video</span>';
                container.style.borderColor = 'rgba(56, 189, 248, 0.5)';
            }, 2200);
        }

        // Populate detected YouTube formats if available
        window.addEventListener('deepx_yt_formats_ready', (e) => {
            const formats = e.detail || [];
            if (!formats || !formats.length) return;
            // Clear default video item and inject dynamic quality items
            itemVideo.style.display = 'none';
            for (const f of formats.slice(0, 4)) {
                const qItem = document.createElement('div');
                qItem.className = 'menu-item';
                qItem.innerHTML = `<span>🎬</span> <span>${f.quality}</span> ${f.size ? '<span class="size-badge">' + f.size + '</span>' : ''}`;
                qItem.onclick = (ev) => {
                    ev.stopPropagation();
                    dropdown.classList.remove('show');
                    triggerDownload('video', f.quality);
                };
                dropdown.insertBefore(qItem, itemAudio);
            }
        });

        mainBtn.onclick = (e) => {
            e.stopPropagation();
            triggerDownload('video');
        };

        arrowBtn.onclick = (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        };

        itemVideo.onclick = (e) => {
            e.stopPropagation();
            dropdown.classList.remove('show');
            triggerDownload('video');
        };

        itemAudio.onclick = (e) => {
            e.stopPropagation();
            dropdown.classList.remove('show');
            triggerDownload('audio');
        };

        itemOpen.onclick = (e) => {
            e.stopPropagation();
            dropdown.classList.remove('show');
            triggerDownload('video');
        };

        document.addEventListener('click', (e) => {
            if (!host.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });

        return host;
    }

    // 4. Multi-Platform Video Scanner
    function scanAndAttachVideoBars() {
        // YouTube Main Player
        if (window.location.hostname.includes('youtube.com')) {
            const ytPlayer = document.getElementById('movie_player') || document.querySelector('.html5-video-player');
            if (ytPlayer && !ytPlayer.querySelector('.deepx-idm-host')) {
                const comp = window.getComputedStyle(ytPlayer);
                if (comp.position === 'static') ytPlayer.style.position = 'relative';
                const bar = createIdmBar(() => window.location.href, () => document.title);
                ytPlayer.appendChild(bar);
            }
        }

        // TikTok Player
        if (window.location.hostname.includes('tiktok.com')) {
            const xg = document.querySelector('.xgplayer-container, div[data-e2e="feed-video"]');
            if (xg && !xg.querySelector('.deepx-idm-host')) {
                const comp = window.getComputedStyle(xg);
                if (comp.position === 'static') xg.style.position = 'relative';
                const bar = createIdmBar(() => window.location.href, () => document.title);
                xg.appendChild(bar);
            }
        }

        // Generic HTML5 Video tags
        const allVideos = document.querySelectorAll('video');
        for (let i = 0; i < allVideos.length; i++) {
            const vid = allVideos[i];
            const p = vid.parentElement;
            if (!p || p.querySelector('.deepx-idm-host')) continue;

            const rect = vid.getBoundingClientRect();
            if (rect.width < 140 || rect.height < 90) continue;

            const comp = window.getComputedStyle(p);
            if (comp.position === 'static') p.style.position = 'relative';

            const bar = createIdmBar(() => {
                if (vid.currentSrc && vid.currentSrc.startsWith('http') && !vid.currentSrc.startsWith('blob:')) {
                    return vid.currentSrc;
                }
                return window.location.href;
            }, () => document.title);
            p.appendChild(bar);
        }
    }

    // Run scanner periodically & on mutations
    setInterval(scanAndAttachVideoBars, 1500);
    const observer = new MutationObserver(scanAndAttachVideoBars);
    observer.observe(document.documentElement, { childList: true, subtree: true });
})();
