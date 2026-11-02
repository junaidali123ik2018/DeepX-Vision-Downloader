// DeepX Vision Downloader - Background Service Worker
const CANDIDATE_PORTS = [18932, 18933, 18934, 18935];
const NATIVE_HOST = 'com.deepx.downloader';

// Store detected media per tab
const mediaByTab = new Map();

async function sendDownloadToApp(url, title, mediaType, quality = "Best Available") {
    console.log('[DeepX Extension] Sending download to app:', url, mediaType, quality);
    let sent = false;

    // 1. Try local HTTP IPC server
    for (const port of CANDIDATE_PORTS) {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2000);
            const res = await fetch(`http://127.0.0.1:${port}/download`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    url: url,
                    title: title || "",
                    media_type: mediaType || "video",
                    quality: quality || "Best Available",
                    browser: "Chrome/Edge Extension"
                }),
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (res.ok) {
                console.log(`[DeepX Extension] Successfully queued on port ${port}`);
                sent = true;
                break;
            }
        } catch (e) {
            // Try next candidate port
        }
    }

    // 2. Try Native Messaging Host if HTTP is offline or blocked
    if (!sent && chrome.runtime.sendNativeMessage) {
        try {
            chrome.runtime.sendNativeMessage(NATIVE_HOST, {
                action: "download",
                url: url,
                title: title,
                media_type: mediaType,
                quality: quality
            }, (response) => {
                if (chrome.runtime.lastError) {
                    console.log('[DeepX Extension] Native messaging unavailable:', chrome.runtime.lastError.message);
                } else {
                    console.log('[DeepX Extension] Native host response:', response);
                }
            });
        } catch (e) {}
    }

    return sent;
}

// Context Menu Setup
chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: "deepx_download_video",
        title: "⚡ Download Video with DeepX",
        contexts: ["video", "link", "page"]
    });
    chrome.contextMenus.create({
        id: "deepx_download_audio",
        title: "🎵 Download Audio (MP3) with DeepX",
        contexts: ["video", "audio", "link", "page"]
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    const targetUrl = info.srcUrl || info.linkUrl || info.pageUrl || tab?.url;
    if (!targetUrl) return;

    if (info.menuItemId === "deepx_download_video") {
        sendDownloadToApp(targetUrl, tab?.title, "video");
    } else if (info.menuItemId === "deepx_download_audio") {
        sendDownloadToApp(targetUrl, tab?.title, "audio");
    }
});

// Sniff media requests (MP4, WEBM, M3U8, MP3)
if (chrome.webRequest && chrome.webRequest.onBeforeRequest) {
    chrome.webRequest.onBeforeRequest.addListener(
        (details) => {
            if (details.tabId < 0) return;
            const url = details.url;
            if (/\.(mp4|webm|mkv|mov|mp3|m4a|m3u8)(\?.*)?$/i.test(url)) {
                let tabMedia = mediaByTab.get(details.tabId) || [];
                if (!tabMedia.some(item => item.url === url)) {
                    tabMedia.push({
                        url: url,
                        type: url.includes('.mp3') || url.includes('.m4a') ? 'audio' : 'video',
                        timestamp: Date.now()
                    });
                    if (tabMedia.length > 30) tabMedia.shift();
                    mediaByTab.set(details.tabId, tabMedia);
                }
            }
        },
        { urls: ["<all_urls>"] }
    );
}

// Clean up tab media cache on navigation or closure
chrome.tabs.onRemoved.addListener((tabId) => {
    mediaByTab.delete(tabId);
});

// Message listener from content script or popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "download") {
        sendDownloadToApp(request.url, request.title, request.media_type, request.quality).then(res => {
            sendResponse({ success: res });
        });
        return true;
    }
    if (request.action === "get_tab_media") {
        const tabId = request.tabId || sender.tab?.id;
        const media = mediaByTab.get(tabId) || [];
        sendResponse({ media: media });
        return true;
    }
});
