// LIMS Samples Page - JavaScript Logic

(function() {
    'use strict';

    // State
    let samples = [];
    let selectedSample = null;

    // DOM Elements
    const samplesList = document.getElementById('samples-list');
    const runPipelineModal = document.getElementById('run-pipeline-modal');
    const modalSampleId = document.getElementById('modal-sample-id');
    const confirmRunBtn = document.getElementById('confirm-run-btn');

    /**
     * Initialize the page
     */
    function init() {
        // Check authentication (allows local dev mode)
        if (!Auth.requireAuth()) return;

        // Initialize navigation
        Nav.init();

        // Setup modal handlers
        UI.setupModalHandlers();

        // Bind modal confirm button
        confirmRunBtn.addEventListener('click', handleConfirmRun);

        // Load samples
        loadSamples();
    }

    /**
     * Load samples from API
     */
    async function loadSamples() {
        UI.showLoading(samplesList, 'Loading samples...');

        try {
            const data = await Api.getSamples();
            samples = data.samples || [];
            renderSamples();
        } catch (error) {
            console.error('Failed to load samples:', error);
            UI.showError(samplesList, error.message || 'Failed to load samples');
        }
    }

    /**
     * Render samples table
     */
    function renderSamples() {
        if (samples.length === 0) {
            samplesList.innerHTML = UI.emptyState(
                'No samples registered',
                'No samples found in the LIMS registry',
                `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                </svg>`
            );
            return;
        }

        const canRunPipeline = Auth.hasRole('operator');

        samplesList.innerHTML = `
            <div class="samples-table-container">
                <table class="samples-table">
                    <thead>
                        <tr>
                            <th>Sample ID</th>
                            <th>Project</th>
                            <th>Description</th>
                            <th>Type</th>
                            <th>Pipeline Status</th>
                            <th>Updated</th>
                            ${canRunPipeline ? '<th>Action</th>' : ''}
                        </tr>
                    </thead>
                    <tbody>
                        ${samples.map(s => renderSampleRow(s, canRunPipeline)).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Bind action buttons
        bindActionButtons();
    }

    /**
     * Render a single sample row
     */
    function renderSampleRow(sample, canRunPipeline) {
        const status = sample.PipelineStatus || 'NOT_STARTED';
        const canRun = canRunPipeline && (status === 'NOT_STARTED' || status === 'WORKFLOW_FAILED');
        const updatedAt = sample.UpdatedAt || sample.CreatedAt;

        return `
            <tr>
                <td>
                    <a href="status.html?sample_id=${encodeURIComponent(sample.SampleID)}" style="color: var(--primary); font-family: var(--font-mono); font-weight: 600; text-decoration: none;">
                        ${UI.escapeHtml(sample.SampleID)}
                    </a>
                </td>
                <td>${UI.escapeHtml(sample.ProjectID || '-')}</td>
                <td class="desc-cell">${UI.escapeHtml(sample.Description || '-')}</td>
                <td><span class="badge badge-type">${UI.escapeHtml(sample.AnalysisType || 'WGS')}</span></td>
                <td>${UI.statusBadge(status)}</td>
                <td class="text-muted">${UI.formatRelativeTime(updatedAt)}</td>
                ${canRunPipeline ? `
                    <td>
                        ${canRun
                            ? `<button class="btn btn-primary btn-sm" data-action="run-pipeline" data-sample-id="${UI.escapeHtml(sample.SampleID)}">Run Pipeline</button>`
                            : `<span class="text-muted">-</span>`
                        }
                    </td>
                ` : ''}
            </tr>
        `;
    }

    /**
     * Bind action button click handlers
     */
    function bindActionButtons() {
        document.querySelectorAll('[data-action="run-pipeline"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const sampleId = btn.dataset.sampleId;
                openRunPipelineModal(sampleId);
            });
        });
    }

    /**
     * Open run pipeline modal
     */
    function openRunPipelineModal(sampleId) {
        selectedSample = samples.find(s => s.SampleID === sampleId);
        if (!selectedSample) return;

        modalSampleId.textContent = sampleId;
        confirmRunBtn.disabled = false;
        confirmRunBtn.textContent = 'Start Pipeline';

        UI.openModal('run-pipeline-modal');
    }

    /**
     * Handle confirm run button click
     */
    async function handleConfirmRun() {
        if (!selectedSample) return;

        confirmRunBtn.disabled = true;
        confirmRunBtn.textContent = 'Starting...';

        try {
            await Api.startPipeline(selectedSample);

            UI.closeModal('run-pipeline-modal');
            UI.showToast(`Pipeline started for ${selectedSample.SampleID}`, 'success');

            // Refresh the list to show updated status
            loadSamples();
        } catch (error) {
            console.error('Failed to start pipeline:', error);
            UI.showToast(error.message || 'Failed to start pipeline', 'error');

            confirmRunBtn.disabled = false;
            confirmRunBtn.textContent = 'Start Pipeline';
        }
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
