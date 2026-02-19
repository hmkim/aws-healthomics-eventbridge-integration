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
};
