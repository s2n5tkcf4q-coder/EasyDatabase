// static/js/chat.js

/**
 * 企业数据分析智能体 - 问答页面交互逻辑
 * 依赖：main.js (showToast, scrollToBottom, 复制功能)
 */

document.addEventListener('DOMContentLoaded', function () {
    // 缓存 DOM 元素
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    const historyList = document.getElementById('chat-history-list');
    const newSessionBtn = document.getElementById('new-session-btn');

    // 当前会话 ID（从 Flask session 获取或空）
    let currentSessionId = null;

    // ========== 初始化 ==========
    init();

    async function init() {
        // 加载历史会话列表
        await loadHistoryList();
        // 聚焦输入框
        if (chatInput) chatInput.focus();
        // 绑定事件
        bindEvents();
        // 如果有默认 session 或者最近一个会话，自动加载
        if (currentSessionId) {
            await loadSessionMessages(currentSessionId);
        }
    }

    // ========== 事件绑定 ==========
    function bindEvents() {
        // 发送消息
        sendBtn.addEventListener('click', handleSendMessage);
        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
            }
        });

        // 新建会话
        newSessionBtn.addEventListener('click', handleNewSession);

        // 历史列表事件委托
        historyList.addEventListener('click', function(e) {
            const item = e.target.closest('.chat-history-item');
            if (item) {
                const sessionId = item.dataset.sessionId;
                if (sessionId) {
                    loadSessionMessages(sessionId);
                }
            }

            // 删除按钮
            const deleteBtn = e.target.closest('.delete-session-btn');
            if (deleteBtn) {
                e.stopPropagation();
                const sessionId = deleteBtn.dataset.sessionId;
                if (confirm('确定要删除此对话记录吗？')) {
                    deleteSession(sessionId);
                }
            }
        });
    }

    // ========== 发送消息 ==========
    async function handleSendMessage() {
        const message = chatInput.value.trim();
        if (!message) return;

        // 禁用发送按钮，显示加载状态
        setSendingState(true);
        chatInput.value = '';

        // 添加用户消息气泡
        appendMessage('user', message);

        try {
            const response = await fetch('/chat/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || '请求失败');
            }

            const data = await response.json();

            // 更新当前会话 ID
            if (data.session_id) {
                currentSessionId = data.session_id;
                // 重新加载历史会话列表（突出当前）
                await loadHistoryList();
            }

            // 渲染助手回复（包含思维链、答案、文件下载）
            appendAssistantMessage(data);

        } catch (error) {
            showToast(error.message, 'danger');
            appendMessage('assistant', '抱歉，处理请求时出错：' + error.message, true);
        } finally {
            setSendingState(false);
            // 滚动到底部
            window.scrollToBottom('.chat-messages');
        }
    }

    function setSendingState(sending) {
        sendBtn.disabled = sending;
        sendBtn.innerHTML = sending ? '<span class="spinner-border spinner-border-sm"></span> 思考中...' : '发送';
        chatInput.disabled = sending;
    }

    // ========== 添加消息 ==========
    function appendMessage(role, content, isError = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        if (isError) messageDiv.classList.add('error-message');

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.innerHTML = formatContent(content); // 简单处理换行

        messageDiv.appendChild(bubble);

        // 添加操作按钮（复制）
        if (role === 'assistant' && !isError) {
            const actions = document.createElement('div');
            actions.className = 'message-actions';
            const copyBtn = document.createElement('button');
            copyBtn.className = 'btn btn-sm btn-outline-secondary copy-btn';
            copyBtn.textContent = '复制';
            actions.appendChild(copyBtn);
            messageDiv.appendChild(actions);
        }

        chatMessages.appendChild(messageDiv);
        window.scrollToBottom('.chat-messages');
    }

    function appendAssistantMessage(data) {
        // 创建一个复合助手消息
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';

        // 1. 思维链区域（可折叠）
        if (data.thinking_chain && data.thinking_chain.length > 0) {
            const thinkingDiv = document.createElement('div');
            thinkingDiv.className = 'thinking-chain';
            const details = document.createElement('details');
            const summary = document.createElement('summary');
            summary.innerHTML = '<span>🔍 智能体Agent (共 ' + data.thinking_chain.length + ' 步)</span>';
            details.appendChild(summary);

            // 构建步骤列表
            const stepList = document.createElement('div');
            stepList.className = 'thinking-steps';
            data.thinking_chain.forEach(step => {
                const stepDiv = document.createElement('div');
                stepDiv.className = 'thinking-step';

                const statusClass = {
                    'success': 'status-success',
                    'failed': 'status-failed',
                    'pending': 'status-pending'
                }[step.status] || '';

                stepDiv.innerHTML = `
                    <span class="step-id">步骤 ${step.step_id}</span>
                    <span class="${statusClass}">[${step.status}]</span>
                    <span>${escapeHtml(step.description)}</span>
                `;

                if (step.detail) {
                    const detailDiv = document.createElement('div');
                    detailDiv.className = 'step-detail';
                    detailDiv.textContent = step.detail;
                    stepDiv.appendChild(detailDiv);
                }

                stepList.appendChild(stepDiv);
            });
            details.appendChild(stepList);
            thinkingDiv.appendChild(details);
            messageDiv.appendChild(thinkingDiv);
        }

        // 2. 答案区域
        const answerBubble = document.createElement('div');
        answerBubble.className = 'message-bubble';
        answerBubble.innerHTML = formatMarkdown(data.answer || '分析完成，详见智能体Agent。');
        messageDiv.appendChild(answerBubble);

        // 3. 文件下载链接
        if (data.file_url && data.file_name) {
            const downloadLink = document.createElement('a');
            downloadLink.className = 'file-download';
            downloadLink.href = data.file_url;
            downloadLink.download = data.file_name;
            const ext = data.file_name.split('.').pop().toUpperCase();
            downloadLink.innerHTML = `<span>📥</span> 下载 ${ext} 文件`;
            messageDiv.appendChild(downloadLink);
        }

        // 4. 操作按钮
        const actions = document.createElement('div');
        actions.className = 'message-actions';
        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn btn-sm btn-outline-secondary copy-btn';
        copyBtn.textContent = '复制';
        actions.appendChild(copyBtn);
        messageDiv.appendChild(actions);

        chatMessages.appendChild(messageDiv);
    }

    // ========== 加载历史会话列表 ==========
    async function loadHistoryList() {
        try {
            const resp = await fetch('/chat/history');
            if (!resp.ok) throw new Error('加载历史记录失败');
            const sessions = await resp.json();
            renderHistoryList(sessions);
        } catch (e) {
            console.error(e);
            showToast('加载历史记录失败', 'danger');
        }
    }

    function renderHistoryList(sessions) {
        historyList.innerHTML = '';
        if (sessions.length === 0) {
            historyList.innerHTML = '<div class="text-muted p-3 text-center">暂无聊天记录</div>';
            return;
        }
        sessions.forEach(sess => {
            const item = document.createElement('div');
            item.className = 'chat-history-item' + (sess.session_id === currentSessionId ? ' active' : '');
            item.dataset.sessionId = sess.session_id;
            item.innerHTML = `
                <div class="d-flex justify-content-between align-items-start">
                    <div class="session-summary flex-grow-1">${escapeHtml(sess.summary)}</div>
                    <button class="btn btn-sm btn-outline-danger delete-session-btn" data-session-id="${sess.session_id}" title="删除">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
                <div class="session-time">${formatTime(sess.last_time)}</div>
            `;
            historyList.appendChild(item);
        });
    }

    // ========== 加载指定会话消息 ==========
    async function loadSessionMessages(sessionId) {
        try {
            const resp = await fetch(`/chat/history/${sessionId}`);
            if (!resp.ok) throw new Error('加载消息失败');
            const messages = await resp.json();

            // 更新当前会话 ID
            currentSessionId = sessionId;
            // 高亮历史列表
            document.querySelectorAll('.chat-history-item').forEach(item => {
                item.classList.toggle('active', item.dataset.sessionId === sessionId);
            });

            // 清空当前聊天区
            chatMessages.innerHTML = '';

            // 重新渲染消息（这里简单处理，不包含思维链折叠状态，从 extra_info 恢复）
            messages.forEach(msg => {
                if (msg.role === 'user') {
                    appendMessage('user', msg.content);
                } else if (msg.role === 'assistant') {
                    // 尝试从 extra_info 恢复思维链
                    let thinkingChain = null;
                    if (msg.extra_info) {
                        try {
                            const extra = typeof msg.extra_info === 'string' ? JSON.parse(msg.extra_info) : msg.extra_info;
                            thinkingChain = extra.thinking_chain;
                        } catch (e) {}
                    }
                    // 构造类似 send API 返回的数据结构
                    let fileUrl = null;
                    let fileName = null;
                    if (msg.extra_info) {
                        try {
                            const extra = typeof msg.extra_info === 'string' ? JSON.parse(msg.extra_info) : msg.extra_info;
                            thinkingChain = extra.thinking_chain;
                            fileUrl = extra.file_url;
                            fileName = extra.file_name;
                        } catch (e) {}
                    }
                    const data = {
                        answer: msg.content,
                        thinking_chain: thinkingChain || [],
                        file_url: fileUrl,
                        file_name: fileName
                    };
                    appendAssistantMessage(data);
                }
                // 系统消息忽略
            });
            window.scrollToBottom('.chat-messages');
        } catch (e) {
            console.error(e);
            showToast('加载消息失败', 'danger');
        }
    }

    // ========== 删除会话 ==========
    async function deleteSession(sessionId) {
        try {
            const resp = await fetch(`/chat/history/${sessionId}/delete`, { method: 'POST' });
            if (!resp.ok) throw new Error('删除失败');
            showToast('对话已删除', 'success');

            // 如果删除的是当前会话，清空界面
            if (currentSessionId === sessionId) {
                currentSessionId = null;
                chatMessages.innerHTML = '';
            }
            await loadHistoryList();
        } catch (e) {
            console.error(e);
            showToast('删除失败', 'danger');
        }
    }

    // ========== 新建会话 ==========
    async function handleNewSession() {
        try {
            const resp = await fetch('/chat/new_session', { method: 'POST' });
            if (!resp.ok) throw new Error('操作失败');
            const data = await resp.json();
            currentSessionId = data.session_id;
            chatMessages.innerHTML = '';
            // 重新加载历史列表
            await loadHistoryList();
            showToast('新会话已创建', 'info');
        } catch (e) {
            console.error(e);
            showToast('创建新会话失败', 'danger');
        }
    }

    // ========== 工具函数 ==========
    function formatContent(text) {
        if (!text) return '';
        // 简单处理换行，不渲染 HTML 以免 XSS
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function formatMarkdown(text) {
        if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
            // 降级：仅转义并保留换行
            return escapeHtml(text).replace(/\n/g, '<br>');
        }
        const rawHtml = marked.parse(text);
        return DOMPurify.sanitize(rawHtml);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatTime(isoString) {
        if (!isoString) return '';
        const date = new Date(isoString);
        const now = new Date();
        const diff = now - date;
        if (diff < 60000) return '刚刚';
        if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
        if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
        return date.toLocaleDateString();
    }
});