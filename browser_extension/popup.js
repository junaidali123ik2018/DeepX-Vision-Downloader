// DeepX Vision Downloader - Popup Script
document.addEventListener('DOMContentLoaded', async () => {
    const CANDIDATE_PORTS = [18932, 18933, 18934, 18935];
    const appStatusEl = document.getElementById('appStatus');
    const pageTitleEl = document.getElementById('pageTitle');
    const btnVideo = document.getElementById('btnDownloadVideo');
    const btnAudio = document.getElementById('btnDownloadAudio');
    const btnOpen = document.getElementById('btnOpenApp');
    const mediaListEl = document.getElementById('mediaList');

    let currentTab = null;

    // Check App Connectivity
    async function checkApp() {
        for (const port of CANDIDATE_PORTS) {
            try {
                const res = await fetch(`http://127.0.0.1:${port}/status`, { method: 'GET' });
                if (res.ok) {
                    appStatusEl.textContent = 'App Connected';
                    appStatusEl.style.color = '#34d399';
                    appStatusEl.style.borderColor = 'rgba(16, 185, 129, 0.4)';
                    return port;
                }
            } catch (e) {}
        }
        appStatusEl.textContent = 'App Idle';
        appStatusEl.style.color = '#f59e0b';
        appStatusEl.style.borderColor = 'rgba(245, 158, 11, 0.4)';
        return null;
    }

    const activePort = await checkApp();

    // Get Active Tab
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs && tabs[0]) {
        currentTab = tabs[0];
        pageTitleEl.textContent = currentTab.title || currentTab.url;
    }

    // Download Video Button
    btnVideo.onclick = () => {
        if (!currentTab) return;
        chrome.runtime.sendMessage({
            action: 'download',
            url: currentTab.url,
            title: currentTab.title,
            media_type: 'video'
        });
        btnVideo.textContent = '✓ Queued in DeepX!';
        btnVideo.style.background = '#10b981';
        setTimeout(() => window.close(), 1200);
    };

    // Download Audio Button
    btnAudio.onclick = () => {
        if (!currentTab) return;
        chrome.runtime.sendMessage({
            action: 'download',
            url: currentTab.url,
            title: currentTab.title,
            media_type: 'audio'
        });
        btnAudio.textContent = '✓ Queued Audio!';
        btnAudio.style.background = '#10b981';
        setTimeout(() => window.close(), 1200);
    };

    // Focus Main App Window
    btnOpen.onclick = () => {
        for (const port of CANDIDATE_PORTS) {
            fetch(`http://127.0.0.1:${port}/focus`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'focus_main' })
            }).catch(() => {});
        }
        window.close();
    };

    // Retrieve detected media for this tab
    if (currentTab && currentTab.id) {
        chrome.runtime.sendMessage({ action: 'get_tab_media', tabId: currentTab.id }, (res) => {
            const list = res?.media || [];
            if (list.length > 0) {
                mediaListEl.innerHTML = '';
                for (const item of list) {
                    const row = document.createElement('div');
                    row.className = 'btn btn-secondary';
                    row.style.fontSize = '10px';
                    row.style.padding = '5px 8px';
                    row.style.justifyContent = 'space-between';
                    row.innerHTML = `<span>${item.type === 'audio' ? '🎵' : '🎬'} ${item.url.split('/').pop().split('?')[0].substring(0, 24)}…</span> <span>Download ▾</span>`;
                    row.onclick = () => {
                        chrome.runtime.sendMessage({
                            action: 'download',
                            url: item.url,
                            title: currentTab.title,
                            media_type: item.type
                        });
                        row.innerHTML = '<span>✓ Added to DeepX</span>';
                    };
                    mediaListEl.appendChild(row);
                }
            }
        });
    }
});
