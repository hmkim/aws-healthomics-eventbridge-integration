// LIMS Genomics Dashboard - Main Application

(function() {
    'use strict';

    // State
    const state = {
        currentView: 'status',
        pendingApprovals: [],
        selectedApproval: null,
        approvalDecision: null,
        isLoading: false,
    };

    // DOM Elements
    const elements = {};

    // Initialize application
    function init() {
        cacheElements();
        loadSettings();
        bindEvents();
        showView('status');
    }

    // Cache DOM elements
    function cacheElements() {
        elements.navItems = document.querySelectorAll('.nav-item[data-view]');
        elements.views = document.querySelectorAll('.view');
        elements.settingsBtn = document.getElementById('settings-btn');
        elements.settingsModal = document.getElementById('settings-modal');
        elements.settingsForm = document.getElementById('settings-form');
        elements.apiUrlInput = document.getElementById('api-url');
        elements.apiKeyInput = document.getElementById('api-key');
        elements.searchForm = document.getElementById('search-form');
        elements.sampleIdInput = document.getElementById('sample-id');
        elements.searchResults = document.getElementById('search-results');
        elements.approvalsList = document.getElementById('approvals-list');
        elements.approvalModal = document.getElementById('approval-modal');
        elements.approvalForm = document.getElementById('approval-form');
        elements.approvalSampleId = document.getElementById('approval-sample-id');
        elements.approverNameInput = document.getElementById('approver-name');
        elements.approvalReasonInput = document.getElementById('approval-reason');
        elements.approvalSubmitBtn = document.getElementById('approval-submit-btn');
        elements.toastContainer = document.getElementById('toast-container');
    }

    // Load settings from localStorage (with config.js fallback for CloudFront deployment)
    function loadSettings() {
        const config = window.LIMS_CONFIG || {};
        const apiUrl = localStorage.getItem('lims_api_url') || config.apiUrl || '';
        const apiKey = localStorage.getItem('lims_api_key') || '';

        elements.apiUrlInput.value = apiUrl;
        elements.apiKeyInput.value = apiKey;

        ApiClient.configure(apiUrl, apiKey);
    }

    // Save settings to localStorage
    function saveSettings(apiUrl, apiKey) {
        localStorage.setItem('lims_api_url', apiUrl);
        localStorage.setItem('lims_api_key', apiKey);
        ApiClient.configure(apiUrl, apiKey);
    }

    // Bind event listeners
    function bindEvents() {
        // Navigation
        elements.navItems.forEach(item => {
            item.addEventListener('click', () => {
                const view = item.dataset.view;
                showView(view);
            });
        });

        // Settings modal
        elements.settingsBtn.addEventListener('click', () => openModal('settings-modal'));
        elements.settingsForm.addEventListener('submit', handleSettingsSave);

        // Search form
        elements.searchForm.addEventListener('submit', handleSearch);

        // Approval form
        elements.approvalForm.addEventListener('submit', handleApprovalSubmit);

        // Modal close buttons
        document.querySelectorAll('.modal-close, [data-dismiss="modal"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const modal = btn.closest('.modal-backdrop');
                if (modal) closeModal(modal.id);
            });
        });

        // Close modal on backdrop click
        document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
            backdrop.addEventListener('click', (e) => {
                if (e.target === backdrop) closeModal(backdrop.id);
            });
        });

        // Close modal on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal-backdrop.active').forEach(modal => {
                    closeModal(modal.id);
                });
            }
        });
    }

    // Show view
    function showView(viewName) {
        state.currentView = viewName;

        // Update nav items
        elements.navItems.forEach(item => {
            item.classList.toggle('active', item.dataset.view === viewName);
        });

        // Update views
        elements.views.forEach(view => {
            view.classList.toggle('active', view.id === `${viewName}-view`);
        });

        // Load data for specific views
        if (viewName === 'approvals') {
            loadPendingApprovals();
        }
    }

    // Open modal
    function openModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            const firstInput = modal.querySelector('input:not([type="hidden"])');
            if (firstInput) setTimeout(() => firstInput.focus(), 100);
        }
    }

    // Close modal
    function closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
        }
    }

    // Handle settings save
    function handleSettingsSave(e) {
        e.preventDefault();
        const apiUrl = elements.apiUrlInput.value.trim();
        const apiKey = elements.apiKeyInput.value.trim();

        saveSettings(apiUrl, apiKey);
        closeModal('settings-modal');
        showToast('Settings saved successfully', 'success');
    }

    // Handle search
    async function handleSearch(e) {
        e.preventDefault();
        const sampleId = elements.sampleIdInput.value.trim();

        if (!sampleId) {
            showToast('Please enter a sample ID', 'error');
            return;
        }

        if (!ApiClient.baseUrl) {
            showToast('Please configure API settings first', 'error');
            openModal('settings-modal');
            return;
        }

        elements.searchResults.innerHTML = renderLoading();

        try {
            const data = await ApiClient.getStatus(sampleId);
            elements.searchResults.innerHTML = renderStatusResult(data);
        } catch (error) {
            elements.searchResults.innerHTML = renderError(
                error.message || 'Failed to fetch sample status'
            );
        }
    }

    // Load pending approvals
    async function loadPendingApprovals() {
        if (!ApiClient.baseUrl) {
            elements.approvalsList.innerHTML = renderError(
                'Please configure API settings to view pending approvals'
            );
            return;
        }

        elements.approvalsList.innerHTML = renderLoading();

        try {
            const data = await ApiClient.getPendingApprovals();
            state.pendingApprovals = data.pending_approvals || [];
            elements.approvalsList.innerHTML = renderApprovalsList(state.pendingApprovals);
            bindApprovalButtons();
        } catch (error) {
            elements.approvalsList.innerHTML = renderError(
                error.message || 'Failed to fetch pending approvals'
            );
        }
    }

    // Bind approval buttons
    function bindApprovalButtons() {
        document.querySelectorAll('[data-action="approve"], [data-action="reject"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const sampleId = btn.dataset.sampleId;
                const action = btn.dataset.action;
                openApprovalModal(sampleId, action);
            });
        });
    }

    // Open approval modal
    function openApprovalModal(sampleId, decision) {
        state.selectedApproval = sampleId;
        state.approvalDecision = decision;

        elements.approvalSampleId.textContent = sampleId;
        elements.approverNameInput.value = '';
        elements.approvalReasonInput.value = '';

        // Update button style based on decision
        elements.approvalSubmitBtn.className = decision === 'approve'
            ? 'btn btn-success'
            : 'btn btn-danger';
        elements.approvalSubmitBtn.textContent = decision === 'approve' ? 'Approve' : 'Reject';

        // Update modal title
        document.querySelector('#approval-modal .modal-title').textContent =
            decision === 'approve' ? 'Approve Sample' : 'Reject Sample';

        openModal('approval-modal');
    }

    // Handle approval submit
    async function handleApprovalSubmit(e) {
        e.preventDefault();

        const approverName = elements.approverNameInput.value.trim();
        const reason = elements.approvalReasonInput.value.trim();

        if (!approverName) {
            showToast('Please enter your name', 'error');
            return;
        }

        elements.approvalSubmitBtn.disabled = true;
        elements.approvalSubmitBtn.textContent = 'Processing...';

        try {
            await ApiClient.submitApproval(
                state.selectedApproval,
                state.approvalDecision,
                approverName,
                reason
            );

            closeModal('approval-modal');
            showToast(
                `Sample ${state.selectedApproval} ${state.approvalDecision}d successfully`,
                'success'
            );

            // Refresh the list
            loadPendingApprovals();
        } catch (error) {
            showToast(error.message || 'Failed to submit approval', 'error');
        } finally {
            elements.approvalSubmitBtn.disabled = false;
            elements.approvalSubmitBtn.textContent =
                state.approvalDecision === 'approve' ? 'Approve' : 'Reject';
        }
    }

    // Render loading state
    function renderLoading() {
        return `
            <div class="loading-state">
                <div class="spinner"></div>
                <p class="loading-text">Loading...</p>
            </div>
        `;
    }

    // Render error message
    function renderError(message) {
        return `
            <div class="error-message">
                ${escapeHtml(message)}
            </div>
        `;
    }

    // Render status result
    function renderStatusResult(data) {
        const records = data.records || [];

        if (records.length === 0) {
            return `
                <div class="empty-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="11" cy="11" r="8"/>
                        <path d="M21 21l-4.35-4.35"/>
                    </svg>
                    <p class="empty-state-title">No records found</p>
                    <p class="empty-state-text">No analysis records found for this sample ID</p>
                </div>
            `;
        }

        const latestRecord = records[0];
        const status = latestRecord.Status || latestRecord.status || 'INITIALIZED';
        const statusClass = status.toLowerCase().replace(/ /g, '_');

        return `
            <div class="result-card">
                <div class="result-header">
                    <div class="result-sample-id">${escapeHtml(latestRecord.SampleID || data.sample_id)}</div>
                    <div class="result-meta">${records.length} record${records.length !== 1 ? 's' : ''} found</div>
                </div>
                <div class="result-body">
                    <div class="timeline">
                        ${records.map(record => renderTimelineItem(record)).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    // Render timeline item
    function renderTimelineItem(record) {
        const status = record.Status || record.status || 'INITIALIZED';
        const statusClass = status.toLowerCase().replace(/ /g, '_');
        const step = record.AnalysisType || record.analysis_type || 'Processing';
        const timestamp = formatTimestamp(record.UpdatedAt || record.updated_at || record.Timestamp || record.timestamp);

        let details = [];
        if (record.GATKRunId) details.push(`GATK Run: <code>${escapeHtml(record.GATKRunId)}</code>`);
        if (record.VEPRunId) details.push(`VEP Run: <code>${escapeHtml(record.VEPRunId)}</code>`);
        if (record.ProjectID) details.push(`Project: <code>${escapeHtml(record.ProjectID)}</code>`);
        if (record.ApprovedBy) details.push(`Approved by: ${escapeHtml(record.ApprovedBy)}`);
        if (record.ApprovalReason) details.push(`Reason: ${escapeHtml(record.ApprovalReason)}`);

        return `
            <div class="timeline-item status-${statusClass}">
                <div class="timeline-header">
                    <span class="timeline-step">${escapeHtml(step)}</span>
                    <span class="badge badge-${statusClass}">${escapeHtml(status)}</span>
                </div>
                <div class="timeline-time">${timestamp}</div>
                ${details.length > 0 ? `
                    <div class="timeline-details">
                        ${details.join(' &bull; ')}
                    </div>
                ` : ''}
            </div>
        `;
    }

    // Render approvals list
    function renderApprovalsList(approvals) {
        if (approvals.length === 0) {
            return `
                <div class="empty-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                        <polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                    <p class="empty-state-title">All caught up!</p>
                    <p class="empty-state-text">No samples pending approval</p>
                </div>
            `;
        }

        return `
            <div class="approvals-grid">
                ${approvals.map(item => renderApprovalCard(item)).join('')}
            </div>
        `;
    }

    // Render approval card
    function renderApprovalCard(item) {
        const sampleId = item.SampleID || item.sample_id;
        const timestamp = formatTimestamp(item.UpdatedAt || item.updated_at || item.Timestamp);
        const projectId = item.ProjectID || item.project_id || 'Unknown';

        return `
            <div class="approval-card">
                <div class="approval-info">
                    <div class="approval-sample-id">${escapeHtml(sampleId)}</div>
                    <div class="approval-meta">
                        <span>Project: ${escapeHtml(projectId)}</span>
                        <span>Submitted: ${timestamp}</span>
                    </div>
                </div>
                <div class="approval-actions">
                    <button class="btn btn-success btn-sm" data-action="approve" data-sample-id="${escapeHtml(sampleId)}">
                        Approve
                    </button>
                    <button class="btn btn-danger btn-sm" data-action="reject" data-sample-id="${escapeHtml(sampleId)}">
                        Reject
                    </button>
                </div>
            </div>
        `;
    }

    // Show toast notification
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;

        elements.toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // Format timestamp
    function formatTimestamp(timestamp) {
        if (!timestamp) return 'Unknown';

        try {
            const date = new Date(timestamp);
            return date.toLocaleString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return timestamp;
        }
    }

    // Escape HTML
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
