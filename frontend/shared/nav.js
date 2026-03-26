// Navigation module for LIMS Genomics Dashboard
// Renders consistent navigation across all pages

const Nav = {
    // Navigation items configuration
    items: [
        { id: 'samples', label: 'LIMS Samples', href: 'samples.html', minRole: 'viewer' },
        { id: 'status', label: 'Pipeline Status', href: 'status.html', minRole: 'viewer' },
        { id: 'approvals', label: 'Pending Approvals', href: 'approvals.html', minRole: 'admin' },
        { id: 'results', label: 'Approved Results', href: 'results.html', minRole: 'admin' }
    ],

    /**
     * Initialize navigation - render nav bar and set up user info
     */
    init() {
        this._render();
        this._setActiveLink();
        this._setupEventListeners();
    },

    /**
     * Determine active page from current URL
     */
    getActivePage() {
        const path = window.location.pathname;
        const filename = path.split('/').pop() || 'index.html';

        for (const item of this.items) {
            if (filename === item.href) {
                return item.id;
            }
        }
        return 'samples';
    },

    _render() {
        const navContainer = document.querySelector('.nav');
        if (!navContainer) {
            console.error('Nav container not found');
            return;
        }

        const user = Auth.getUser();
        const displayName = user?.display_name || user?.email || 'User';
        const activePage = this.getActivePage();

        // Filter items based on user role
        const visibleItems = this.items.filter(item => Auth.hasRole(item.minRole));

        navContainer.innerHTML = `
            <div class="nav-brand">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                </svg>
                <span>LIMS Genomics Dashboard</span>
            </div>

            <div class="nav-items">
                ${visibleItems.map(item => `
                    <a href="${item.href}" class="nav-item ${activePage === item.id ? 'active' : ''}">
                        ${UI.escapeHtml(item.label)}
                    </a>
                `).join('')}
            </div>

            <div class="nav-actions">
                <span class="nav-user" style="color: var(--text-muted); font-size: 0.875rem; margin-right: 12px;">
                    ${UI.escapeHtml(displayName)}
                </span>
                <button class="icon-btn" id="logout-btn" title="Logout">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                        <polyline points="16 17 21 12 16 7"/>
                        <line x1="21" y1="12" x2="9" y2="12"/>
                    </svg>
                </button>
            </div>
        `;
    },

    _setActiveLink() {
        const path = window.location.pathname;
        const filename = path.split('/').pop() || 'index.html';

        document.querySelectorAll('.nav-item').forEach(link => {
            const href = link.getAttribute('href');
            if (href === filename) {
                link.classList.add('active');
            }
        });
    },

    _setupEventListeners() {
        const logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', (e) => {
                e.preventDefault();
                if (confirm('Are you sure you want to logout?')) {
                    Auth.logout();
                }
            });
        }
    }
};
