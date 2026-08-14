// Configuration
let API_BASE = '';

let currentCategory = '';
let searchQuery = '';
let searchTimeout = null;
let articlesList = [];

// DOM Elements
const newsGrid = document.getElementById('news-grid');
const searchInput = document.getElementById('search-input');
const categoryTabs = document.getElementById('category-tabs');
const articlesCountEl = document.getElementById('articles-count');
const emptyStateEl = document.getElementById('empty-state');
const errorStateEl = document.getElementById('error-state');
const themeToggleBtn = document.getElementById('theme-toggle-btn');
const fetchTriggerBtn = document.getElementById('fetch-trigger-btn');
const clearSearchBtn = document.getElementById('clear-search-btn');
const retryBtn = document.getElementById('retry-btn');
const toastEl = document.getElementById('toast');
const toastMessageEl = document.getElementById('toast-message');

// ==========================================================================
// APP INITIALIZATION
// ==========================================================================

async function initConfig() {
    try {
        const response = await fetch('./config.json');
        if (response.ok) {
            const config = await response.json();
            API_BASE = config.apiBaseUrl || '';
        } else {
            throw new Error(`Failed to load config: ${response.status}`);
        }
    } catch (error) {
        console.warn('Could not load config.json, using default API configuration.', error);
        // Fallback for local development
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            API_BASE = 'http://127.0.0.1:8000';
        } else {
            API_BASE = '';
        }
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    await initConfig();
    loadNews();
    setupEventListeners();
});


function setupEventListeners() {
    // Search input event with debouncing (300ms)
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchQuery = e.target.value.trim();
        searchTimeout = setTimeout(() => {
            loadNews();
        }, 300);
    });

    // Keyboard shortcut for search focus (Cmd/Ctrl + K)
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            searchInput.focus();
        }
    });

    // Category Tabs click events
    categoryTabs.addEventListener('click', (e) => {
        const btn = e.target.closest('.tab-btn');
        if (!btn) return;
        
        categoryTabs.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        
        currentCategory = btn.dataset.category;
        loadNews();
    });

    // Theme toggle button
    themeToggleBtn.addEventListener('click', toggleTheme);

    // Sync News manual fetch trigger
    fetchTriggerBtn.addEventListener('click', triggerManualFetch);

    // Empty state reset button
    clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        searchQuery = '';
        currentCategory = '';
        categoryTabs.querySelectorAll('.tab-btn').forEach(t => {
            if (t.dataset.category === '') t.classList.add('active');
            else t.classList.remove('active');
        });
        loadNews();
    });

    // Error state retry button
    retryBtn.addEventListener('click', loadNews);
}

// ==========================================================================
// THEME HANDLING (DARK / LIGHT)
// ==========================================================================

function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    if (savedTheme === 'light') {
        document.body.classList.remove('dark-theme');
        document.body.classList.add('light-theme');
        themeToggleBtn.innerHTML = '<i class="fa-solid fa-moon"></i>';
    } else {
        document.body.classList.remove('light-theme');
        document.body.classList.add('dark-theme');
        themeToggleBtn.innerHTML = '<i class="fa-solid fa-sun"></i>';
    }
}

function toggleTheme() {
    if (document.body.classList.contains('dark-theme')) {
        document.body.classList.remove('dark-theme');
        document.body.classList.add('light-theme');
        themeToggleBtn.innerHTML = '<i class="fa-solid fa-moon"></i>';
        localStorage.setItem('theme', 'light');
    } else {
        document.body.classList.remove('light-theme');
        document.body.classList.add('dark-theme');
        themeToggleBtn.innerHTML = '<i class="fa-solid fa-sun"></i>';
        localStorage.setItem('theme', 'dark');
    }
}

// ==========================================================================
// DATA FETCHING & RENDERING
// ==========================================================================

async function loadNews() {
    showLoadingSkeletons();
    hideStates();
    
    let queryParams = new URLSearchParams();
    if (currentCategory) queryParams.append('category', currentCategory);
    if (searchQuery) queryParams.append('search', searchQuery);
    queryParams.append('limit', '30');
    
    const url = `${API_BASE}/api/news?${queryParams.toString()}`;
    
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        const data = await response.json();
        articlesList = data.articles || [];
        
        renderNews();
    } catch (error) {
        console.error('Failed to load news:', error);
        newsGrid.innerHTML = '';
        errorStateEl.classList.remove('hidden');
        articlesCountEl.textContent = 'Error loading news';
    }
}

function renderNews() {
    newsGrid.innerHTML = '';
    
    if (articlesList.length === 0) {
        emptyStateEl.classList.remove('hidden');
        articlesCountEl.textContent = '0 articles found';
        return;
    }
    
    articlesCountEl.textContent = `Showing ${articlesList.length} articles`;
    
    articlesList.forEach((article, index) => {
        const card = document.createElement('article');
        card.className = 'news-card';
        card.style.animationDelay = `${index * 0.05}s`;
        
        const friendlyTime = formatRelativeTime(article.published_at);
        const catBadgeClass = `badge badge-${article.category.toLowerCase()}`;
        
        card.innerHTML = `
            <div>
                <div class="card-header">
                    <span class="${catBadgeClass}">${article.category}</span>
                    <span class="card-meta">${article.source} &bull; ${friendlyTime}</span>
                </div>
                <h3 class="card-title">
                    <a href="${article.url}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.title)}</a>
                </h3>
                <p class="card-desc">${escapeHtml(article.description || 'No summary available.')}</p>
            </div>
            <div class="card-footer">
                <span class="trending-score">
                    <i class="fa-solid fa-fire"></i> Trending Score: ${article.score}
                </span>
                <a href="${article.url}" target="_blank" rel="noopener noreferrer" class="card-btn">
                    Read Source <i class="fa-solid fa-arrow-right"></i>
                </a>
            </div>
        `;
        
        newsGrid.appendChild(card);
    });
}

function showLoadingSkeletons() {
    newsGrid.innerHTML = '';
    for (let i = 0; i < 6; i++) {
        const skeletonCard = document.createElement('div');
        skeletonCard.className = 'skeleton-card';
        skeletonCard.innerHTML = `
            <div>
                <div class="card-header">
                    <div class="skeleton-item sk-badge"></div>
                    <div class="skeleton-item sk-meta"></div>
                </div>
                <div class="skeleton-item sk-title-1"></div>
                <div class="skeleton-item sk-title-2"></div>
                <div class="skeleton-item sk-desc-1"></div>
                <div class="skeleton-item sk-desc-2"></div>
            </div>
            <div class="card-footer">
                <div class="skeleton-item sk-footer-left"></div>
                <div class="skeleton-item sk-footer-right"></div>
            </div>
        `;
        newsGrid.appendChild(skeletonCard);
    }
}

function hideStates() {
    emptyStateEl.classList.add('hidden');
    errorStateEl.classList.add('hidden');
}

// ==========================================================================
// ACTIONS & NOTIFICATIONS
// ==========================================================================

async function triggerManualFetch() {
    fetchTriggerBtn.classList.add('spin-anim');
    fetchTriggerBtn.disabled = true;
    
    const adminKey = localStorage.getItem('admin_key') 
        || new URLSearchParams(window.location.search).get('admin_key') 
        || 'default-admin-key';
        
    try {
        const response = await fetch(`${API_BASE}/api/fetch`, {
            method: 'POST',
            headers: {
                'x-api-key': adminKey,
                'Content-Type': 'application/json'
            }
        });
        
        if (response.status === 401) {
            showToast('Unauthorized: Check your admin credentials', 'error');
        } else if (!response.ok) {
            throw new Error(`Status ${response.status}`);
        } else {
            showToast('News sync triggered! Updating in a moment...', 'success');
            setTimeout(loadNews, 5000);
        }
    } catch (error) {
        console.error('Manual fetch trigger failed:', error);
        showToast('Failed to trigger news sync.', 'error');
    } finally {
        fetchTriggerBtn.classList.remove('spin-anim');
        fetchTriggerBtn.disabled = false;
    }
}

function showToast(message, type = 'success') {
    toastMessageEl.textContent = message;
    
    const iconEl = toastEl.querySelector('.toast-icon');
    if (type === 'success') {
        iconEl.className = 'fa-solid fa-circle-check toast-icon';
        iconEl.style.color = '#10b981';
    } else {
        iconEl.className = 'fa-solid fa-circle-xmark toast-icon';
        iconEl.style.color = '#ef4444';
    }
    
    toastEl.classList.remove('hidden');
    
    setTimeout(() => {
        toastEl.classList.add('hidden');
    }, 4000);
}

// ==========================================================================
// UTILITIES
// ==========================================================================

function formatRelativeTime(isoString) {
    if (!isoString) return 'unknown';
    try {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);
        
        if (diffMins < 1) return 'just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays === 1) return 'yesterday';
        if (diffDays < 7) return `${diffDays}d ago`;
        
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (e) {
        return 'recently';
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
