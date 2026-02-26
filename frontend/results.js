// Approved Results Page - JavaScript Logic

(function() {
    'use strict';

    // State
    let approvedResults = [];
    let selectedRecord = null;

    // DOM Elements
    const resultsList = document.getElementById('results-list');
    const sendEmailForm = document.getElementById('send-email-form');
    const modalSampleId = document.getElementById('modal-sample-id');
    const modalSubmitterEmail = document.getElementById('modal-submitter-email');
    const additionalEmailsInput = document.getElementById('additional-emails');
    const sendEmailBtn = document.getElementById('send-email-btn');

    /**
     * Initialize the page
     */
    function init() {
        if (!Auth.requireAuth()) return;
        if (!Auth.requireRole('admin')) return;

        Nav.init();
        UI.setupModalHandlers();

        sendEmailForm.addEventListener('submit', handleSendEmail);

        loadApprovedResults();
    }

    /**
     * Load approved results from API
     */
    async function loadApprovedResults() {
        UI.showLoading(resultsList, 'Loading approved results...');

        try {
            const data = await Api.getApprovedResults();
            approvedResults = data.approved_results || [];
            renderResults();
        } catch (error) {
            console.error('Failed to load results:', error);
            UI.showError(resultsList, error.message || 'Failed to load approved results');
        }
    }

    /**
     * Render results list
     */
    function renderResults() {
        if (approvedResults.length === 0) {
            resultsList.innerHTML = UI.emptyState(
                'No approved results',
                'Approved analysis results will appear here',
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
                '<polyline points="14 2 14 8 20 8"/>' +
                '<line x1="16" y1="13" x2="8" y2="13"/>' +
                '<line x1="16" y1="17" x2="8" y2="17"/>' +
                '</svg>'
            );
            return;
        }

        resultsList.innerHTML = '<div class="approvals-grid">' +
            approvedResults.map(renderResultCard).join('') +
            '</div>';

        bindSendButtons();
    }

    /**
     * Render a single result card
     */
    function renderResultCard(item) {
        const sampleId = item.SampleID || '';
        const projectId = item.ProjectID || 'Unknown';
        const analysisType = item.AnalysisType || 'WGS';
        const approvedBy = item.ApprovedBy || 'Unknown';
        const approvalDate = item.ApprovalDecidedAt || item.UpdatedAt || '';
        const gatkUri = item.GATKOutputUri || '';
        const vepUri = item.VEPOutputUri || '';

        const outputInfo = [];
        if (gatkUri) {
            outputInfo.push(
                '<span>GATK Output: <code style="font-family:var(--font-mono);background:var(--divider);padding:2px 6px;border-radius:var(--radius-sm);font-size:0.8em;">' +
                UI.escapeHtml(gatkUri) + '</code></span>'
            );
        }
        if (vepUri) {
            outputInfo.push(
                '<span>VEP Output: <code style="font-family:var(--font-mono);background:var(--divider);padding:2px 6px;border-radius:var(--radius-sm);font-size:0.8em;">' +
                UI.escapeHtml(vepUri) + '</code></span>'
            );
        }

        const hasOutputs = gatkUri || vepUri;

        return '<div class="approval-card">' +
            '<div class="approval-info">' +
                '<div class="approval-sample-id">' +
                    '<a href="status.html?sample_id=' + encodeURIComponent(sampleId) + '" style="color:inherit;text-decoration:none;">' +
                        UI.escapeHtml(sampleId) +
                    '</a>' +
                    ' ' + UI.statusBadge('COMPLETED_APPROVED') +
                '</div>' +
                '<div class="approval-meta">' +
                    '<span>Project: ' + UI.escapeHtml(projectId) + '</span>' +
                    '<span>Type: <span class="badge badge-type">' + UI.escapeHtml(analysisType) + '</span></span>' +
                    '<span>Approved by: ' + UI.escapeHtml(approvedBy) + '</span>' +
                    '<span>Approved: ' + UI.formatRelativeTime(approvalDate) + '</span>' +
                '</div>' +
                (outputInfo.length > 0 ?
                    '<div class="approval-meta" style="margin-top:8px;">' + outputInfo.join('') + '</div>' : '') +
            '</div>' +
            '<div class="approval-actions">' +
                (hasOutputs ?
                    '<button class="btn btn-primary btn-sm" data-action="send" data-sample-id="' +
                    UI.escapeHtml(sampleId) + '">Send Results Email</button>' :
                    '<span style="color:var(--text-muted);font-size:0.85rem;">No output URIs</span>') +
            '</div>' +
        '</div>';
    }

    /**
     * Bind send button click handlers
     */
    function bindSendButtons() {
        document.querySelectorAll('[data-action="send"]').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var sampleId = btn.dataset.sampleId;
                openSendModal(sampleId);
            });
        });
    }

    /**
     * Open send email modal
     */
    function openSendModal(sampleId) {
        selectedRecord = approvedResults.find(function(r) {
            return r.SampleID === sampleId;
        });
        if (!selectedRecord) return;

        modalSampleId.textContent = sampleId;
        modalSubmitterEmail.value = selectedRecord.SubmitterEmail || '';
        additionalEmailsInput.value = '';
        sendEmailBtn.disabled = false;
        sendEmailBtn.textContent = 'Send';

        UI.openModal('send-email-modal');
    }

    /**
     * Handle send email form submission
     */
    async function handleSendEmail(e) {
        e.preventDefault();
        if (!selectedRecord) return;

        var sampleId = selectedRecord.SampleID;
        var rawEmails = additionalEmailsInput.value.trim();
        var additionalEmails = rawEmails
            ? rawEmails.split(',').map(function(e) { return e.trim(); }).filter(Boolean)
            : [];

        sendEmailBtn.disabled = true;
        sendEmailBtn.textContent = 'Sending...';

        try {
            var result = await Api.sendResultsEmail(sampleId, additionalEmails);
            UI.closeModal('send-email-modal');
            UI.showToast(
                'Results email sent for ' + sampleId + ' to ' +
                (result.recipients ? result.recipients.join(', ') : 'recipients'),
                'success'
            );
        } catch (error) {
            console.error('Failed to send results email:', error);
            UI.showToast(error.message || 'Failed to send results email', 'error');
            sendEmailBtn.disabled = false;
            sendEmailBtn.textContent = 'Send';
        }
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
