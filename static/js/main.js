// static/js/main.js

/**
 * 企业数据分析智能体 - 全局交互逻辑
 * 包含：菜单切换、复制消息、思维链折叠、验证码刷新、会话超时提醒等
 */

document.addEventListener('DOMContentLoaded', function () {

    // ========== 侧边栏菜单激活状态 ==========
    initSidebarMenu();

    // ========== 复制功能 ==========
    initCopyButtons();

    // ========== 思维链折叠控制 ==========
    initThinkingChain();

    // ========== 验证码刷新 ==========
    initCaptchaRefresh();

    // ========== 文件下载链接处理 ==========
    initFileDownload();

    // ========== 会话超时提醒（可选） ==========
    initSessionTimeoutWarning();

    // ========== 其他小功能 ==========
    initTooltips();
    initSmoothScroll();
});

// ----------------------------------------------------------------
// 侧边栏菜单激活
// ----------------------------------------------------------------
function initSidebarMenu() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.admin-sidebar .nav-link, .chat-sidebar .nav-link');

    navLinks.forEach(link => {
        // 根据 href 判断是否当前页面
        const href = link.getAttribute('href');
        if (href && currentPath.startsWith(href)) {
            link.classList.add('active');
        }

        // 点击时添加过渡效果
        link.addEventListener('click', function(e) {
            // 如果是导航链接，可显示加载状态
            if (link.classList.contains('nav-link')) {
                // 可以在这里添加加载指示器（非必需）
            }
        });
    });
}

// ----------------------------------------------------------------
// 复制按钮（用于消息气泡）
// ----------------------------------------------------------------
function initCopyButtons() {
    // 动态生成的复制按钮通过事件委托处理
    document.addEventListener('click', function(e) {
        const copyBtn = e.target.closest('.copy-btn');
        if (!copyBtn) return;

        // 获取要复制的文本：从最近的 .message-bubble 或指定 data-target
        let targetText = '';
        const targetSelector = copyBtn.getAttribute('data-copy-target');
        if (targetSelector) {
            const targetEl = document.querySelector(targetSelector);
            if (targetEl) targetText = targetEl.innerText;
        } else {
            // 默认复制所在消息气泡内容
            const bubble = copyBtn.closest('.message-bubble');
            if (bubble) targetText = bubble.innerText;
        }

        if (!targetText) return;

        // 使用 Clipboard API 复制
        navigator.clipboard.writeText(targetText).then(() => {
            showToast('已复制到剪贴板', 'success');
        }).catch(err => {
            // 降级方案：创建 textarea
            const textarea = document.createElement('textarea');
            textarea.value = targetText;
            textarea.style.position = 'fixed';
            textarea.style.left = '-9999px';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                showToast('已复制到剪贴板', 'success');
            } catch (ex) {
                showToast('复制失败，请手动复制', 'danger');
            }
            document.body.removeChild(textarea);
        });
    });
}

// ----------------------------------------------------------------
// 思维链折叠动画
// ----------------------------------------------------------------
function initThinkingChain() {
    // 为所有的 details 元素添加打开/关闭时的高度动画（CSS 已处理）
    // 这里可添加自定义事件监听，比如记录思维链展开次数（用于分析）
    document.querySelectorAll('.thinking-chain details').forEach(details => {
        details.addEventListener('toggle', function() {
            if (this.open) {
                // 思维链展开，可以发送统计日志（如果需要）
                console.debug('思维链已展开:', this.querySelector('summary')?.textContent?.trim());
            }
        });
    });
}

// ----------------------------------------------------------------
// 验证码刷新
// ----------------------------------------------------------------
function initCaptchaRefresh() {
    const captchaImg = document.getElementById('captcha-img');
    if (!captchaImg) return;

    captchaImg.addEventListener('click', function() {
        // 添加时间戳避免缓存
        const timestamp = new Date().getTime();
        this.src = '/captcha?t=' + timestamp;
    });

    // 也可以加一个刷新按钮
    const refreshBtn = document.getElementById('captcha-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', function() {
            const img = document.getElementById('captcha-img');
            if (img) {
                img.src = '/captcha?t=' + new Date().getTime();
            }
        });
    }
}

// ----------------------------------------------------------------
// 文件下载链接处理（在新标签页打开或提示）
// ----------------------------------------------------------------
function initFileDownload() {
    // 对带 .file-download 类的链接，如果是图片可预览
    document.addEventListener('click', function(e) {
        const link = e.target.closest('.file-download');
        if (!link) return;

        const href = link.getAttribute('href');
        if (!href) return;

        // 如果是图片格式，在新窗口预览（或模态框）
        if (/\.(png|jpg|jpeg|gif|svg|bmp)$/i.test(href)) {
            e.preventDefault();
            window.open(href, '_blank');
        }
        // 其他类型（excel, word, ppt, html）直接下载，由浏览器处理
    });
}

// ----------------------------------------------------------------
// 会话超时提醒（在页面显示倒计时或定时检查）
// ----------------------------------------------------------------
function initSessionTimeoutWarning() {
    // 从配置获取超时时间（秒），如果没有则默认3600
    let timeoutSeconds = 3600;
    const configElement = document.getElementById('session-timeout-config');
    if (configElement) {
        timeoutSeconds = parseInt(configElement.dataset.timeout) || 3600;
    }

    // 上次活动时间存储在 sessionStorage
    const lastActivityKey = 'last_activity_time';
    const warningKey = 'timeout_warning_shown';

    // 更新最后活动时间
    function updateActivity() {
        sessionStorage.setItem(lastActivityKey, Date.now().toString());
        sessionStorage.removeItem(warningKey);
    }

    // 监听用户活动
    ['click', 'keypress', 'scroll', 'mousemove'].forEach(event => {
        document.addEventListener(event, updateActivity, { passive: true });
    });

    // 定期检查是否即将超时
    setInterval(() => {
        const lastActivity = parseInt(sessionStorage.getItem(lastActivityKey) || '0');
        if (!lastActivity) return;

        const now = Date.now();
        const elapsed = (now - lastActivity) / 1000; // 秒
        const remaining = timeoutSeconds - elapsed;

        // 在剩余5分钟和1分钟时提醒
        if (remaining <= 300 && remaining > 0 && !sessionStorage.getItem(warningKey)) {
            showToast(`会话将在 ${Math.ceil(remaining / 60)} 分钟后过期，请保存工作`, 'warning');
            sessionStorage.setItem(warningKey, 'shown');
        }

        if (remaining <= 0) {
            // 会话已过期，可主动跳转
            sessionStorage.removeItem(lastActivityKey);
            window.location.href = '/login?expired=1';
        }
    }, 30000); // 每30秒检查一次
}

// ----------------------------------------------------------------
// 提示工具初始化 (Bootstrap Tooltip 替代)
// ----------------------------------------------------------------
function initTooltips() {
    // 简单实现：为带 data-tooltip 属性的元素添加 title 提示
    document.querySelectorAll('[data-tooltip]').forEach(el => {
        el.setAttribute('title', el.getAttribute('data-tooltip'));
    });
}

// ----------------------------------------------------------------
// 平滑滚动到页面底部（用于聊天消息更新）
// ----------------------------------------------------------------
function initSmoothScroll() {
    // 暴露全局函数供 chat.js 调用
    window.scrollToBottom = function(containerSelector) {
        const container = document.querySelector(containerSelector || '.chat-messages');
        if (container) {
            container.scrollTo({
                top: container.scrollHeight,
                behavior: 'smooth'
            });
        }
    };
}

// ----------------------------------------------------------------
// Toast 消息提示（轻量级，不依赖 Bootstrap）
// ----------------------------------------------------------------
function showToast(message, type = 'info') {
    // 创建 toast 容器（如果不存在）
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;';
        document.body.appendChild(toastContainer);
    }

    // 背景色
    const bgColors = {
        success: '#10b981',
        danger: '#ef4444',
        warning: '#f59e0b',
        info: '#3b82f6'
    };
    const bgColor = bgColors[type] || bgColors.info;

    const toast = document.createElement('div');
    toast.className = 'toast-item';
    toast.textContent = message;
    toast.style.cssText = `
        background: ${bgColor};
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        margin-bottom: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        font-size: 0.9rem;
        opacity: 0;
        transform: translateX(100%);
        transition: all 0.3s ease;
    `;

    toastContainer.appendChild(toast);

    // 触发动画
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(0)';
    });

    // 自动移除
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }, 3000);
}

// 将 showToast 挂载到全局，便于其他脚本调用
window.showToast = showToast;

// ----------------------------------------------------------------
// 通用 AJAX 错误处理（可选）
// ----------------------------------------------------------------
window.handleAjaxError = function(error, defaultMsg = '请求失败') {
    let message = defaultMsg;
    if (error.responseJSON && error.responseJSON.error) {
        message = error.responseJSON.error;
    } else if (error.statusText) {
        message = error.statusText;
    }
    showToast(message, 'danger');
};