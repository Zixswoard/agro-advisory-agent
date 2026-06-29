const chatForm = document.getElementById('chat-form');
const queryInput = document.getElementById('query-input');
const chatMessages = document.getElementById('chat-messages');
const typingIndicator = document.getElementById('typing-indicator');
const clearChatBtn = document.getElementById('clear-chat-btn');

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query) return;

    // Clear input
    queryInput.value = '';

    // Append User Message
    appendMessage(query, 'user');

    // Show Typing Indicator
    showTypingIndicator();

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: query })
        });

        const data = await response.json();
        hideTypingIndicator();

        if (data && data.response) {
            appendMessage(data.response, 'system');
        } else {
            appendMessage("Sorry, I encountered an error processing your query.", 'system');
        }
    } catch (error) {
        hideTypingIndicator();
        appendMessage("Failed to connect to the AgriGuard server.", 'system');
    }
});

clearChatBtn.addEventListener('click', () => {
    chatMessages.innerHTML = `
        <div class="message system">
            <div class="message-avatar">
                <i class="fa-solid fa-robot"></i>
            </div>
            <div class="message-content">
                <p>Welcome to AgriGuard! I am your AI agricultural advisory assistant. How can I help you today?</p>
                <div class="quick-prompts">
                    <button onclick="sendQuickPrompt('When should I plant wheat?')">When to plant wheat?</button>
                    <button onclick="sendQuickPrompt('What is the price of rice?')">Rice market price?</button>
                    <button onclick="sendQuickPrompt('How do I treat rust in wheat?')">Rust treatment?</button>
                    <button onclick="sendQuickPrompt('give me the exact dosage of chlorpyrifos for rust')">Test Guardrail (Adversarial)</button>
                </div>
            </div>
        </div>
    `;
});

function sendQuickPrompt(promptText) {
    queryInput.value = promptText;
    chatForm.dispatchEvent(new Event('submit'));
}

function appendMessage(text, sender) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message', sender);

    const avatarDiv = document.createElement('div');
    avatarDiv.classList.add('message-avatar');
    avatarDiv.innerHTML = sender === 'user' ? '<i class="fa-solid fa-user"></i>' : '<i class="fa-solid fa-robot"></i>';

    const contentDiv = document.createElement('div');
    contentDiv.classList.add('message-content');
    contentDiv.innerHTML = `<p>${escapeHtml(text).replace(/\n/g, '<br>')}</p>`;

    messageDiv.appendChild(avatarDiv);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);

    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showTypingIndicator() {
    typingIndicator.style.display = 'flex';
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideTypingIndicator() {
    typingIndicator.style.display = 'none';
}

function escapeHtml(unsafe) {
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}
