// API client for LIMS Genomics Orchestration
const ApiClient = {
    baseUrl: '',
    apiKey: '',

    configure(baseUrl, apiKey) {
        this.baseUrl = baseUrl.replace(/\/$/, '');
        this.apiKey = apiKey;
    },

    async request(method, path, body = null) {
        const headers = {
            'Content-Type': 'application/json',
        };
        if (this.apiKey) headers['x-api-key'] = this.apiKey;

        const opts = { method, headers };
        if (body) opts.body = JSON.stringify(body);

        const response = await fetch(`${this.baseUrl}${path}`, opts);
        const data = await response.json();
        if (!response.ok) throw { status: response.status, ...data };
        return data;
    },

    getStatus(sampleId) {
        return this.request('GET', `/analysis/status/${sampleId}`);
    },

    getPendingApprovals() {
        return this.request('GET', '/admin/pending');
    },

    submitApproval(sampleId, decision, approvedBy, reason = '') {
        // Normalize decision to APPROVED/REJECTED as expected by backend
        const normalizedDecision = decision === 'approve' ? 'APPROVED' : 'REJECTED';
        return this.request('POST', '/admin/approve', {
            sample_id: sampleId,
            decision: normalizedDecision,
            approved_by: approvedBy,
            reason,
        });
    },

    getLimsSamples() {
        return this.request('GET', '/lims/samples');
    },

    startPipeline(sample) {
        return this.request('POST', '/analysis/start', {
            source: sample.Source || 'ClarityLIMS_Mock',
            event_type: 'StepCompleted',
            data: {
                project_id: sample.ProjectID,
                sample_id: sample.SampleID,
                patient_id: sample.PatientID,
                submitter_email: sample.SubmitterEmail,
                fastq_paths: { r1: sample.FastqR1, r2: sample.FastqR2 },
                reference_genome: sample.ReferenceGenome,
                analysis_type: sample.AnalysisType,
            },
        });
    },
};
