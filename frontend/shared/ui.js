// UI utilities for LIMS Genomics Dashboard
// Common UI components and helpers

const UI = {
    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(str) {
        if (str === null || str === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    },

    /**
     * Format ISO date string to human readable
     */
    formatDate(isoString) {
        if (!isoString) return '-';

        try {
            const date = new Date(isoString);
            if (isNaN(date.getTime())) return '-';

            return date.toLocaleString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (e) {
            return '-';
        }
    },

    /**
     * Format relative time (e.g., "2 hours ago")
     */
    formatRelativeTime(isoString) {
        if (!isoString) return '-';

        try {
            const date = new Date(isoString);
            if (isNaN(date.getTime())) return '-';

            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return 'Just now';
            if (diffMins < 60) return `${diffMins}m ago`;
            if (diffHours < 24) return `${diffHours}h ago`;
            if (diffDays < 7) return `${diffDays}d ago`;

            return this.formatDate(isoString);
        } catch (e) {
            return '-';
        }
    },

    /**
     * Generate status badge HTML
     */
    statusBadge(status) {
        if (!status) return '<span class="badge">-</span>';

        const statusStr = String(status);
        const normalized = statusStr.toLowerCase().replace(/[_\s]/g, '_');

        return `<span class="badge badge-${this.escapeHtml(normalized)}">${this.escapeHtml(statusStr)}</span>`;
    },

    /**
     * Show loading spinner HTML
     */
    loadingSpinner(text = 'Loading...') {
        return `
            <div class="loading-state">
                <div class="spinner"></div>
                <p class="loading-text">${this.escapeHtml(text)}</p>
            </div>
        `;
    },

    /**
     * Show loading spinner in container
     */
    showLoading(container, text = 'Loading...') {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }
        if (!container) return;

        container.innerHTML = this.loadingSpinner(text);
    },

    /**
     * Create error message HTML
     */
    errorMessage(message) {
        return `
            <div class="error-message">
                ${this.escapeHtml(message)}
            </div>
        `;
    },

    /**
     * Show error message in container
     */
    showError(container, message) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }
        if (!container) return;

        container.innerHTML = this.errorMessage(message);
    },

    /**
     * Create empty state HTML
     */
    emptyState(title, text, iconHtml = null) {
        const defaultIcon = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <path d="M8 12h8M12 8v8"/>
            </svg>
        `;
        return `
            <div class="empty-state">
                ${iconHtml || defaultIcon}
                <p class="empty-state-title">${this.escapeHtml(title)}</p>
                <p class="empty-state-text">${this.escapeHtml(text)}</p>
            </div>
        `;
    },

    /**
     * Show empty state in container
     */
    showEmpty(container, title, text) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }
        if (!container) return;

        container.innerHTML = this.emptyState(title, text);
    },

    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;

        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    },

    /**
     * Open modal by ID
     */
    openModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            const firstInput = modal.querySelector('input:not([type="hidden"]), textarea');
            if (firstInput) {
                setTimeout(() => firstInput.focus(), 100);
            }
        }
    },

    /**
     * Close modal by ID
     */
    closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
        }
    },

    /**
     * Setup modal close handlers (call once on page load)
     */
    setupModalHandlers() {
        // Close on X button or cancel button click
        document.querySelectorAll('.modal-close, [data-dismiss="modal"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const modal = btn.closest('.modal-backdrop');
                if (modal) this.closeModal(modal.id);
            });
        });

        // Close on backdrop click
        document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
            backdrop.addEventListener('click', (e) => {
                if (e.target === backdrop) this.closeModal(backdrop.id);
            });
        });

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal-backdrop.active').forEach(modal => {
                    this.closeModal(modal.id);
                });
            }
        });
    },

    /**
     * Create a confirm dialog and return promise
     */
    async confirm(title, message, confirmText = 'Confirm', confirmClass = 'btn-primary') {
        return new Promise((resolve) => {
            // Create modal if doesn't exist
            let modal = document.getElementById('confirm-modal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'confirm-modal';
                modal.className = 'modal-backdrop';
                modal.innerHTML = `
                    <div class="modal">
                        <div class="modal-header">
                            <h2 class="modal-title" id="confirm-modal-title"></h2>
                            <button class="modal-close" type="button" aria-label="Close">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <line x1="18" y1="6" x2="6" y2="18"/>
                                    <line x1="6" y1="6" x2="18" y2="18"/>
                                </svg>
                            </button>
                        </div>
                        <div class="modal-body">
                            <p id="confirm-modal-message"></p>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" id="confirm-modal-cancel">Cancel</button>
                            <button type="button" class="btn" id="confirm-modal-confirm"></button>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }

            // Set content
            document.getElementById('confirm-modal-title').textContent = title;
            document.getElementById('confirm-modal-message').textContent = message;
            const confirmBtn = document.getElementById('confirm-modal-confirm');
            confirmBtn.textContent = confirmText;
            confirmBtn.className = `btn ${confirmClass}`;

            // Bind handlers
            const cleanup = () => {
                this.closeModal('confirm-modal');
                confirmBtn.onclick = null;
                document.getElementById('confirm-modal-cancel').onclick = null;
                modal.querySelector('.modal-close').onclick = null;
            };

            confirmBtn.onclick = () => {
                cleanup();
                resolve(true);
            };

            document.getElementById('confirm-modal-cancel').onclick = () => {
                cleanup();
                resolve(false);
            };

            modal.querySelector('.modal-close').onclick = () => {
                cleanup();
                resolve(false);
            };

            // Show modal
            this.openModal('confirm-modal');
        });
    },

    /**
     * Get URL parameter
     */
    getUrlParam(name) {
        const params = new URLSearchParams(window.location.search);
        return params.get(name);
    },

    /**
     * Set URL parameter without page reload
     */
    setUrlParam(name, value) {
        const url = new URL(window.location);
        if (value) {
            url.searchParams.set(name, value);
        } else {
            url.searchParams.delete(name);
        }
        window.history.replaceState({}, '', url);
    }
};
