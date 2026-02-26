// Pending Approvals Page - JavaScript Logic

(function() {
    'use strict';

    // State
    let pendingApprovals = [];
    let selectedSampleId = null;
    let selectedDecision = null;

    // DOM Elements
    const approvalsList = document.getElementById('approvals-list');
    const approvalModal = document.getElementById('approval-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalSampleId = document.getElementById('modal-sample-id');
    const approvalForm = document.getElementById('approval-form');
    const approvalReason = document.getElementById('approval-reason');
    const submitBtn = document.getElementById('approval-submit-btn');

    /**
     * Initialize the page
     */
    function init() {
        // Check authentication
        if (!Auth.requireAuth()) return;

        // Check admin role - redirect if not admin
        if (!Auth.requireRole('admin')) return;

        // Initialize navigation
        Nav.init();

        // Setup modal handlers
        UI.setupModalHandlers();

        // Bind form submit
        approvalForm.addEventListener('submit', handleSubmit);

        // Load pending approvals
        loadPendingApprovals();
    }

    /**
     * Load pending approvals from API
     */
    async function loadPendingApprovals() {
        UI.showLoading(approvalsList, 'Loading pending approvals...');

        try {
            const data = await Api.getPendingApprovals();
            pendingApprovals = data.pending_approvals || [];
            renderApprovals();
        } catch (error) {
            console.error('Failed to load approvals:', error);
            UI.showError(approvalsList, error.message || 'Failed to load pending approvals');
        }
    }

    /**
     * Render approvals list
     */
    function renderApprovals() {
        if (pendingApprovals.length === 0) {
            approvalsList.innerHTML = UI.emptyState(
                'All caught up!',
                'No samples pending approval',
                `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>`
            );
            return;
        }

        approvalsList.innerHTML = `
            <div class="approvals-grid">
                ${pendingApprovals.map(item => renderApprovalCard(item)).join('')}
            </div>
        `;

        // Bind action buttons
        bindActionButtons();
    }

    /**
     * Render a single approval card
     */
    function renderApprovalCard(item) {
        const sampleId = item.SampleID || item.sample_id;
        const projectId = item.ProjectID || item.project_id || 'Unknown';
        const submitter = item.SubmitterEmail || item.submitter_email || 'Unknown';
        const timestamp = item.UpdatedAt || item.updated_at || item.Timestamp;
        const analysisType = item.AnalysisType || item.analysis_type || 'WGS';

        return `
            <div class="approval-card">
                <div class="approval-info">
                    <div class="approval-sample-id">
                        <a href="status.html?sample_id=${encodeURIComponent(sampleId)}" style="color: inherit; text-decoration: none;">
                            ${UI.escapeHtml(sampleId)}
                        </a>
                    </div>
                    <div class="approval-meta">
                        <span>Project: ${UI.escapeHtml(projectId)}</span>
                        <span>Submitter: ${UI.escapeHtml(submitter)}</span>
                        <span>Type: <span class="badge badge-type">${UI.escapeHtml(analysisType)}</span></span>
                        <span>Submitted: ${UI.formatRelativeTime(timestamp)}</span>
                    </div>
                    ${item.GATKRunId ? `
                        <div class="approval-meta" style="margin-top: 8px;">
                            <span>GATK Run: <code style="font-family: var(--font-mono); background: var(--divider); padding: 2px 6px; border-radius: var(--radius-sm);">${UI.escapeHtml(item.GATKRunId)}</code></span>
                            ${item.VEPRunId ? `<span>VEP Run: <code style="font-family: var(--font-mono); background: var(--divider); padding: 2px 6px; border-radius: var(--radius-sm);">${UI.escapeHtml(item.VEPRunId)}</code></span>` : ''}
                        </div>
                    ` : ''}
                </div>
                <div class="approval-actions">
                    <button class="btn btn-success btn-sm" data-action="approve" data-sample-id="${UI.escapeHtml(sampleId)}">
                        Approve
                    </button>
                    <button class="btn btn-danger btn-sm" data-action="reject" data-sample-id="${UI.escapeHtml(sampleId)}">
                        Reject
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Bind action button click handlers
     */
    function bindActionButtons() {
        document.querySelectorAll('[data-action="approve"], [data-action="reject"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const sampleId = btn.dataset.sampleId;
                const action = btn.dataset.action;
                openApprovalModal(sampleId, action);
            });
        });
    }

    /**
     * Open approval modal
     */
    function openApprovalModal(sampleId, decision) {
        selectedSampleId = sampleId;
        selectedDecision = decision;

        // Update modal UI based on decision
        modalTitle.textContent = decision === 'approve' ? 'Approve Sample' : 'Reject Sample';
        modalSampleId.textContent = sampleId;
        approvalReason.value = '';

        // Update submit button style
        submitBtn.className = decision === 'approve' ? 'btn btn-success' : 'btn btn-danger';
        submitBtn.textContent = decision === 'approve' ? 'Approve' : 'Reject';
        submitBtn.disabled = false;

        UI.openModal('approval-modal');
    }

    /**
     * Handle form submission
     */
    async function handleSubmit(e) {
        e.preventDefault();

        if (!selectedSampleId || !selectedDecision) return;

        const reason = approvalReason.value.trim();

        submitBtn.disabled = true;
        submitBtn.textContent = 'Processing...';

        try {
            await Api.submitApproval(selectedSampleId, selectedDecision, reason);

            UI.closeModal('approval-modal');
            UI.showToast(
                `Sample ${selectedSampleId} ${selectedDecision === 'approve' ? 'approved' : 'rejected'} successfully`,
                'success'
            );

            // Refresh the list
            loadPendingApprovals();
        } catch (error) {
            console.error('Failed to submit approval:', error);
            UI.showToast(error.message || 'Failed to submit approval', 'error');

            submitBtn.disabled = false;
            submitBtn.textContent = selectedDecision === 'approve' ? 'Approve' : 'Reject';
        }
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
