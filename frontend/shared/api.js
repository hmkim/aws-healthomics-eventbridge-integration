// API client for LIMS Genomics Dashboard
// Handles all API calls with authentication

const Api = {
    /**
     * GET request with authentication
     */
    async get(path) {
        return this._request('GET', path);
    },

    /**
     * POST request with authentication
     */
    async post(path, body) {
        return this._request('POST', path, body);
    },

    /**
     * PUT request with authentication
     */
    async put(path, body) {
        return this._request('PUT', path, body);
    },

    /**
     * DELETE request with authentication
     */
    async delete(path) {
        return this._request('DELETE', path);
    },

    /**
     * Internal request handler with retry logic
     */
    async _request(method, path, body = null, isRetry = false) {
        const config = window.LIMS_CONFIG;
        if (!config || !config.apiUrl) {
            throw new ApiError('API URL not configured', 0);
        }

        const baseUrl = config.apiUrl.replace(/\/$/, '');
        const url = `${baseUrl}${path.startsWith('/') ? path : '/' + path}`;

        const headers = {
            'Content-Type': 'application/json'
        };

        // Add authorization header if authenticated
        const token = Auth.getIdToken();
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        const options = { method, headers };

        if (body && (method === 'POST' || method === 'PUT')) {
            options.body = JSON.stringify(body);
        }

        try {
            const response = await fetch(url, options);

            // Handle 401 - try refresh then redirect
            if (response.status === 401 && !isRetry) {
                const refreshed = await Auth.refreshTokens();
                if (refreshed) {
                    return this._request(method, path, body, true);
                }
                Auth.logout();
                throw new ApiError('Session expired', 401);
            }

            // Handle other errors
            if (!response.ok) {
                const errorData = await this._parseError(response);
                throw new ApiError(
                    errorData.message || errorData.error || response.statusText,
                    response.status,
                    errorData
                );
            }

            // Handle empty responses
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                return null;
            }

            return response.json();
        } catch (error) {
            if (error instanceof ApiError) throw error;
            throw new ApiError(error.message || 'Network error', 0);
        }
    },

    async _parseError(response) {
        try {
            return await response.json();
        } catch {
            return { message: response.statusText };
        }
    },

    // ============ LIMS Samples API ============

    /**
     * Get all LIMS samples for user's organization
     */
    getSamples() {
        return this.get('/lims/samples');
    },

    /**
     * Get a specific sample by ID
     */
    getSample(sampleId) {
        return this.get(`/lims/samples/${encodeURIComponent(sampleId)}`);
    },

    // ============ Analysis API ============

    /**
     * Start pipeline for a sample
     */
    startPipeline(sample) {
        return this.post('/analysis/start', {
            source: sample.Source || 'ClarityLIMS_Mock',
            event_type: 'StepCompleted',
            data: {
                project_id: sample.ProjectID,
                sample_id: sample.SampleID,
                patient_id: sample.PatientID || sample.SampleID,
                submitter_email: sample.SubmitterEmail,
                fastq_paths: { r1: sample.FastqR1, r2: sample.FastqR2 },
                reference_genome: sample.ReferenceGenome,
                analysis_type: sample.AnalysisType
            }
        });
    },

    /**
     * Get pipeline status for a sample
     */
    getStatus(sampleId) {
        return this.get(`/analysis/status/${encodeURIComponent(sampleId)}`);
    },

    // ============ Admin API ============

    /**
     * Get pending approvals
     */
    getPendingApprovals() {
        return this.get('/admin/pending');
    },

    /**
     * Get approved results
     */
    getApprovedResults() {
        return this.get('/admin/results');
    },

    /**
     * Send results email with presigned URLs
     */
    sendResultsEmail(sampleId, additionalEmails = []) {
        return this.post('/admin/results/send', {
            sample_id: sampleId,
            additional_emails: additionalEmails,
        });
    },

    /**
     * Submit approval decision
     */
    submitApproval(sampleId, decision, reason = '') {
        const userInfo = Auth.getUserInfo();
        const approvedBy = userInfo?.email || userInfo?.display_name || 'Unknown';

        // Normalize decision to APPROVED/REJECTED
        const normalizedDecision = decision === 'approve' ? 'APPROVED' : 'REJECTED';

        return this.post('/admin/approve', {
            sample_id: sampleId,
            decision: normalizedDecision,
            approved_by: approvedBy,
            reason: reason
        });
    }
};

/**
 * Custom API error class
 */
class ApiError extends Error {
    constructor(message, status, data = {}) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.data = data;
    }
}

// Alias for backward compatibility
const API = Api;
