// Pipeline Status Page - JavaScript Logic

(function() {
    'use strict';

    // DOM Elements
    const searchForm = document.getElementById('search-form');
    const sampleIdInput = document.getElementById('sample-id-input');
    const statusResults = document.getElementById('status-results');

    /**
     * Initialize the page
     */
    function init() {
        // Check authentication (allows local dev mode)
        if (!Auth.requireAuth()) return;

        // Initialize navigation
        Nav.init();

        // Bind search form
        searchForm.addEventListener('submit', handleSearch);

        // Check for sample_id in URL params
        const sampleId = UI.getUrlParam('sample_id');
        if (sampleId) {
            sampleIdInput.value = sampleId;
            loadStatus(sampleId);
        }
    }

    /**
     * Handle search form submission
     */
    function handleSearch(e) {
        e.preventDefault();

        const sampleId = sampleIdInput.value.trim();
        if (!sampleId) {
            UI.showToast('Please enter a sample ID', 'error');
            return;
        }

        // Update URL with sample_id
        UI.setUrlParam('sample_id', sampleId);

        loadStatus(sampleId);
    }

    /**
     * Load status for a sample
     */
    async function loadStatus(sampleId) {
        UI.showLoading(statusResults, 'Loading status...');

        try {
            const data = await Api.getStatus(sampleId);
            renderStatusResult(data);
        } catch (error) {
            console.error('Failed to load status:', error);

            if (error.status === 404) {
                renderStatusResult({ sample_id: sampleId, records: [], count: 0 });
            } else {
                UI.showError(statusResults, error.message || 'Failed to load sample status');
            }
        }
    }

    /**
     * Render status result card
     */
    function renderStatusResult(data) {
        const records = data.records || [];

        if (records.length === 0) {
            statusResults.innerHTML = UI.emptyState(
                'No records found',
                `No analysis records found for sample "${UI.escapeHtml(data.sample_id)}"`,
                `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="11" cy="11" r="8"/>
                    <path d="M21 21l-4.35-4.35"/>
                </svg>`
            );
            return;
        }

        const latestRecord = records[0];
        const status = latestRecord.Status || latestRecord.status || 'INITIALIZED';

        statusResults.innerHTML = `
            <div class="result-card">
                <div class="result-header">
                    <div class="result-sample-id">${UI.escapeHtml(latestRecord.SampleID || data.sample_id)}</div>
                    <div class="result-meta">${records.length} record${records.length !== 1 ? 's' : ''} found</div>
                </div>
                <div class="result-body">
                    ${renderStatusCards(latestRecord)}
                    <h3 style="font-size: 1rem; margin: 24px 0 16px; color: var(--text-secondary);">Timeline</h3>
                    <div class="timeline">
                        ${records.map(record => renderTimelineItem(record)).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render status info cards
     */
    function renderStatusCards(record) {
        const cards = [];

        // Current status card
        const status = record.Status || record.status || 'INITIALIZED';
        cards.push(`
            <div class="card" style="margin-bottom: 16px;">
                <div class="card-body" style="display: flex; align-items: center; gap: 16px;">
                    <div style="flex: 1;">
                        <div style="font-size: 0.8125rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;">Current Status</div>
                        <div>${UI.statusBadge(status)}</div>
                    </div>
                    ${record.ProjectID ? `
                        <div style="flex: 1;">
                            <div style="font-size: 0.8125rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;">Project</div>
                            <div style="font-weight: 600;">${UI.escapeHtml(record.ProjectID)}</div>
                        </div>
                    ` : ''}
                    ${record.AnalysisType ? `
                        <div style="flex: 1;">
                            <div style="font-size: 0.8125rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;">Analysis Type</div>
                            <div><span class="badge badge-type">${UI.escapeHtml(record.AnalysisType)}</span></div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `);

        // GATK Run card
        if (record.GATKRunId) {
            cards.push(`
                <div class="card" style="margin-bottom: 16px;">
                    <div class="card-body">
                        <div style="font-size: 0.8125rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">GATK Workflow</div>
                        <div style="display: flex; gap: 24px; flex-wrap: wrap;">
                            ${record.GATKRunStatus ? `
                                <div>
                                    <span style="color: var(--text-muted);">Status:</span>
                                    ${UI.statusBadge(record.GATKRunStatus)}
                                </div>
                            ` : ''}
                            <div>
                                <span style="color: var(--text-muted);">Run ID:</span>
                                <code style="font-family: var(--font-mono); background: var(--divider); padding: 2px 6px; border-radius: var(--radius-sm);">${UI.escapeHtml(record.GATKRunId)}</code>
                            </div>
                            ${record.GATKRunName ? `
                                <div>
                                    <span style="color: var(--text-muted);">Run Name:</span>
                                    <span>${UI.escapeHtml(record.GATKRunName)}</span>
                                </div>
                            ` : ''}
                            ${record.GATKStartedAt ? `
                                <div>
                                    <span style="color: var(--text-muted);">Started:</span>
                                    <span>${UI.formatDate(record.GATKStartedAt)}</span>
                                </div>
                            ` : ''}
                            ${record.GATKCompletedAt ? `
                                <div>
                                    <span style="color: var(--text-muted);">Completed:</span>
                                    <span>${UI.formatDate(record.GATKCompletedAt)}</span>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `);
        }

        // VEP Run card
        if (record.VEPRunId) {
            cards.push(`
                <div class="card" style="margin-bottom: 16px;">
                    <div class="card-body">
                        <div style="font-size: 0.8125rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">VEP Workflow</div>
                        <div style="display: flex; gap: 24px; flex-wrap: wrap;">
                            ${record.VEPRunStatus ? `
                                <div>
                                    <span style="color: var(--text-muted);">Status:</span>
                                    ${UI.statusBadge(record.VEPRunStatus)}
                                </div>
                            ` : ''}
                            <div>
                                <span style="color: var(--text-muted);">Run ID:</span>
                                <code style="font-family: var(--font-mono); background: var(--divider); padding: 2px 6px; border-radius: var(--radius-sm);">${UI.escapeHtml(record.VEPRunId)}</code>
                            </div>
                            ${record.VEPRunName ? `
                                <div>
                                    <span style="color: var(--text-muted);">Run Name:</span>
                                    <span>${UI.escapeHtml(record.VEPRunName)}</span>
                                </div>
                            ` : ''}
                            ${record.VEPStartedAt ? `
                                <div>
                                    <span style="color: var(--text-muted);">Started:</span>
                                    <span>${UI.formatDate(record.VEPStartedAt)}</span>
                                </div>
                            ` : ''}
                            ${record.VEPCompletedAt ? `
                                <div>
                                    <span style="color: var(--text-muted);">Completed:</span>
                                    <span>${UI.formatDate(record.VEPCompletedAt)}</span>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `);
        }

        // Approval info card
        if (record.ApprovedBy || record.ApprovalReason) {
            cards.push(`
                <div class="card" style="margin-bottom: 16px;">
                    <div class="card-body">
                        <div style="font-size: 0.8125rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">Approval</div>
                        <div style="display: flex; gap: 24px; flex-wrap: wrap;">
                            ${record.ApprovedBy ? `
                                <div>
                                    <span style="color: var(--text-muted);">Approved by:</span>
                                    <span style="font-weight: 600;">${UI.escapeHtml(record.ApprovedBy)}</span>
                                </div>
                            ` : ''}
                            ${record.ApprovalReason ? `
                                <div>
                                    <span style="color: var(--text-muted);">Reason:</span>
                                    <span>${UI.escapeHtml(record.ApprovalReason)}</span>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `);
        }

        return cards.join('');
    }

    /**
     * Render a timeline item
     */
    function renderTimelineItem(record) {
        const status = record.Status || record.status || 'INITIALIZED';
        const statusClass = status.toLowerCase().replace(/ /g, '_');
        const step = record.AnalysisType || record.analysis_type || 'Processing';
        const timestamp = record.UpdatedAt || record.updated_at || record.Timestamp || record.timestamp;

        const details = [];
        if (record.GATKRunId) details.push(`GATK Run: <code>${UI.escapeHtml(record.GATKRunId)}</code>`);
        if (record.VEPRunId) details.push(`VEP Run: <code>${UI.escapeHtml(record.VEPRunId)}</code>`);
        if (record.ErrorMessage) details.push(`Error: ${UI.escapeHtml(record.ErrorMessage)}`);

        return `
            <div class="timeline-item status-${statusClass}">
                <div class="timeline-header">
                    <span class="timeline-step">${UI.escapeHtml(step)}</span>
                    ${UI.statusBadge(status)}
                </div>
                <div class="timeline-time">${UI.formatDate(timestamp)}</div>
                ${details.length > 0 ? `
                    <div class="timeline-details">
                        ${details.join(' &bull; ')}
                    </div>
                ` : ''}
            </div>
        `;
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
