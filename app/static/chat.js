const messagesElement = document.querySelector("#messages");
const welcomeElement = document.querySelector("#welcome");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat");
const documentSelect = document.querySelector("#document-select");
const fileInput = document.querySelector("#file-input");
const uploadStatus = document.querySelector("#upload-status");
const documentCount = document.querySelector("#document-count");
const conversationList = document.querySelector("#conversation-list");
const conversationCount = document.querySelector("#conversation-count");

let activeConversationId = null;

function addMessage(role, text) {
  if (welcomeElement?.isConnected) welcomeElement.remove();

  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "B" : "T";

  const content = document.createElement("div");
  content.className = "message-content";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  content.append(bubble);

  row.append(avatar, content);
  messagesElement.append(row);
  row.scrollIntoView({ block: "end" });
  return row;
}

function showTyping() {
  const row = addMessage("assistant", "Đang tìm thông tin trong tài liệu");
  row.classList.add("typing");
  const dots = document.createElement("span");
  dots.className = "typing-dots";
  dots.setAttribute("aria-hidden", "true");
  dots.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  row.querySelector(".bubble").append(dots);
  return row;
}

async function loadDocuments() {
  if (activeConversationId === null) return;
  try {
    const response = await fetch(`/documents?conversation_id=${activeConversationId}`);
    if (!response.ok) throw new Error("Không thể tải danh sách tài liệu.");
    const documents = await response.json();
    const selectedId = documentSelect.value;
    documentSelect.replaceChildren(new Option("Tất cả tài liệu", ""));

    for (const document of documents) {
      const option = new Option(document.filename, document.id);
      documentSelect.add(option);
    }
    documentSelect.value = documents.some((item) => String(item.id) === selectedId) ? selectedId : "";
    documentCount.textContent = documents.length;
  } catch (error) {
    uploadStatus.textContent = error.message;
    uploadStatus.classList.add("error");
  }
}

function showWelcome() {
  messagesElement.replaceChildren(welcomeElement);
}

function setConversationNavigationDisabled(disabled) {
  newChatButton.disabled = disabled;
  conversationList.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled;
  });
}

async function loadConversations() {
  const response = await fetch("/conversations");
  if (!response.ok) throw new Error("Không thể tải danh sách cuộc trò chuyện.");
  const conversations = await response.json();
  conversationList.replaceChildren();
  conversationCount.textContent = conversations.length;

  for (const item of conversations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-item";
    button.disabled = sendButton.disabled;
    button.classList.toggle("active", item.id === activeConversationId);
    button.textContent = item.title;
    button.title = item.title;
    button.addEventListener("click", () => {
      openConversation(item.id).catch((error) => {
        uploadStatus.textContent = error.message;
        uploadStatus.classList.add("error");
      });
    });
    conversationList.append(button);
  }
  return conversations;
}

async function openConversation(id) {
  const response = await fetch(`/conversations/${id}`);
  const result = await response.json();
  if (!response.ok) {
    const detail = typeof result.detail === "string" ? result.detail : "Không thể mở cuộc trò chuyện.";
    throw new Error(detail);
  }

  activeConversationId = result.id;
  localStorage.setItem("activeConversationId", String(result.id));
  showWelcome();
  for (const message of result.messages) addMessage(message.role, message.content);
  await Promise.all([loadDocuments(), loadConversations()]);
  input.focus();
}

async function createConversation() {
  const response = await fetch("/conversations", { method: "POST" });
  const result = await response.json();
  if (!response.ok) {
    const detail = typeof result.detail === "string" ? result.detail : "Không thể tạo cuộc trò chuyện mới.";
    throw new Error(detail);
  }

  activeConversationId = result.id;
  localStorage.setItem("activeConversationId", String(result.id));
  documentSelect.value = "";
  showWelcome();
  await Promise.all([loadDocuments(), loadConversations()]);
  input.focus();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || sendButton.disabled) return;

  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  setConversationNavigationDisabled(true);
  let typing;

  try {
    if (activeConversationId === null) await createConversation();
    addMessage("user", message);
    typing = showTyping();
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: activeConversationId,
        document_id: documentSelect.value ? Number(documentSelect.value) : null,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = typeof result.detail === "string" ? result.detail : "Chatbot không thể xử lý câu hỏi.";
      throw new Error(detail);
    }

    typing.remove();
    addMessage("assistant", result.reply);
    loadConversations().catch((error) => {
      uploadStatus.textContent = error.message;
      uploadStatus.classList.add("error");
    });
  } catch (error) {
    typing?.remove();
    addMessage("assistant", `Xin lỗi, đã xảy ra lỗi: ${error.message}`);
    loadConversations().catch((refreshError) => {
      uploadStatus.textContent = refreshError.message;
      uploadStatus.classList.add("error");
    });
  } finally {
    sendButton.disabled = false;
    setConversationNavigationDisabled(false);
    input.focus();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

newChatButton.addEventListener("click", () => {
  createConversation().catch((error) => {
    uploadStatus.textContent = error.message;
    uploadStatus.classList.add("error");
  });
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.textContent;
    form.requestSubmit();
  });
});

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  uploadStatus.classList.remove("error");
  uploadStatus.textContent = `Đang xử lý ${file.name}...`;

  try {
    if (activeConversationId === null) await createConversation();
    const body = new FormData();
    body.append("file", file);
    body.append("conversation_id", String(activeConversationId));
    const response = await fetch("/documents/upload", { method: "POST", body });
    const result = await response.json();
    if (!response.ok) {
      const detail = typeof result.detail === "string" ? result.detail : "Không thể tải tài liệu lên.";
      throw new Error(detail);
    }
    await loadDocuments();
    await loadConversations();
    documentSelect.value = String(result.id);
    uploadStatus.textContent = `Đã sẵn sàng: ${result.filename}`;
  } catch (error) {
    uploadStatus.textContent = error.message;
    uploadStatus.classList.add("error");
  } finally {
    fileInput.value = "";
  }
});

async function initialize() {
  try {
    const conversations = await loadConversations();
    const savedId = Number(localStorage.getItem("activeConversationId"));
    const savedConversation = conversations.find((item) => item.id === savedId);
    if (savedConversation) {
      await openConversation(savedConversation.id);
    } else if (conversations.length) {
      await openConversation(conversations[0].id);
    }
  } catch (error) {
    uploadStatus.textContent = error.message;
    uploadStatus.classList.add("error");
  }
}

initialize();
