// Authentication module for LIMS Genomics Dashboard
// Handles Cognito OAuth2 flow

const Auth = {
    STORAGE_KEYS: {
        ID_TOKEN: 'lims_id_token',
        ACCESS_TOKEN: 'lims_access_token',
        REFRESH_TOKEN: 'lims_refresh_token',
        RETURN_PATH: 'lims_return_path',
        USER_INFO: 'lims_user_info'
    },

    /**
     * Initialize auth - check for valid session
     * On index.html: redirect to Cognito or samples.html
     * On other pages: just validate session
     */
    init() {
        const config = window.LIMS_CONFIG;

        // If no Cognito config, allow local dev mode
        if (!config || !config.cognitoHostedUiDomain) {
            console.warn('Cognito not configured - running in local dev mode');
            return true;
        }

        const token = this.getIdToken();
        const isLoggedIn = token && !this._isTokenExpired(token);

        // Check if on index.html (landing page)
        const isLandingPage = window.location.pathname.endsWith('index.html') ||
                              window.location.pathname === '/' ||
                              window.location.pathname.endsWith('/');

        if (isLandingPage) {
            if (isLoggedIn) {
                // Already logged in, redirect to samples
                window.location.href = 'samples.html';
            } else {
                // Not logged in, redirect to Cognito
                this._redirectToLogin('samples.html');
            }
            return false;
        }

        return isLoggedIn;
    },

    /**
     * Get stored ID token
     */
    getIdToken() {
        return sessionStorage.getItem(this.STORAGE_KEYS.ID_TOKEN);
    },

    /**
     * Get stored access token
     */
    getAccessToken() {
        return sessionStorage.getItem(this.STORAGE_KEYS.ACCESS_TOKEN);
    },

    /**
     * Check if user is authenticated
     */
    isAuthenticated() {
        const token = this.getIdToken();
        return token && !this._isTokenExpired(token);
    },

    /**
     * Decode JWT and return user info
     */
    getUser() {
        // Check cache first
        const cached = sessionStorage.getItem(this.STORAGE_KEYS.USER_INFO);
        if (cached) {
            try {
                return JSON.parse(cached);
            } catch (e) {
                // Fall through to parse from token
            }
        }

        const token = this.getIdToken();
        if (!token) return null;

        try {
            const payload = this._decodeJwt(token);
            const userInfo = {
                sub: payload.sub,
                email: payload.email,
                organization_id: payload['custom:organization_id'] || payload.organization_id,
                groups: payload['cognito:groups'] || [],
                roles: payload['custom:roles'] ? payload['custom:roles'].split(',') : ['viewer'],
                display_name: payload.name || payload.email?.split('@')[0] || 'User'
            };

            // Cache user info
            sessionStorage.setItem(this.STORAGE_KEYS.USER_INFO, JSON.stringify(userInfo));
            return userInfo;
        } catch (e) {
            console.error('Failed to decode JWT:', e);
            return null;
        }
    },

    /**
     * Get user info (alias for getUser for compatibility)
     */
    getUserInfo() {
        return this.getUser();
    },

    /**
     * Check if user has required role (admin > operator > viewer)
     */
    hasRole(required) {
        const hierarchy = ['viewer', 'operator', 'admin'];
        const user = this.getUser();
        if (!user) return false;

        // Check cognito groups
        const groups = (user.groups || []).map(g => g.toLowerCase());

        // Also check custom:roles claim
        const roles = (user.roles || []).map(r => r.toLowerCase());

        const allRoles = [...new Set([...groups, ...roles])];
        const requiredLevel = hierarchy.indexOf(required.toLowerCase());

        for (const role of allRoles) {
            const userLevel = hierarchy.indexOf(role);
            if (userLevel >= requiredLevel) return true;
        }

        // Default: viewers can view
        if (requiredLevel === 0 && user.email) return true;

        return false;
    },

    /**
     * Handle OAuth callback - exchange code for tokens
     */
    async handleCallback() {
        const params = new URLSearchParams(window.location.search);
        const code = params.get('code');
        const state = params.get('state');
        const error = params.get('error');

        if (error) {
            console.error('OAuth error:', error, params.get('error_description'));
            throw new Error(params.get('error_description') || error);
        }

        if (!code) {
            throw new Error('No authorization code received');
        }

        const config = window.LIMS_CONFIG;
        if (!config || !config.cognitoHostedUiDomain) {
            throw new Error('Cognito not configured');
        }

        const tokenUrl = `${config.cognitoHostedUiDomain}/oauth2/token`;

        const body = new URLSearchParams({
            grant_type: 'authorization_code',
            client_id: config.cognitoClientId,
            redirect_uri: config.callbackUrl,
            code: code
        });

        const response = await fetch(tokenUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: body.toString()
        });

        if (!response.ok) {
            const errorData = await response.text();
            console.error('Token exchange failed:', errorData);
            throw new Error('Failed to exchange authorization code');
        }

        const tokens = await response.json();

        // Store tokens
        sessionStorage.setItem(this.STORAGE_KEYS.ID_TOKEN, tokens.id_token);
        sessionStorage.setItem(this.STORAGE_KEYS.ACCESS_TOKEN, tokens.access_token);
        if (tokens.refresh_token) {
            sessionStorage.setItem(this.STORAGE_KEYS.REFRESH_TOKEN, tokens.refresh_token);
        }

        // Clear cached user info so it's re-parsed from new token
        sessionStorage.removeItem(this.STORAGE_KEYS.USER_INFO);

        // Return the page to redirect to (from state param or default)
        return state || 'samples.html';
    },

    /**
     * Logout - clear session and redirect to Cognito logout
     */
    logout() {
        const config = window.LIMS_CONFIG;

        // Clear all stored auth data
        Object.values(this.STORAGE_KEYS).forEach(key => {
            sessionStorage.removeItem(key);
        });

        // Redirect to Cognito logout if configured
        if (config && config.cognitoHostedUiDomain && config.logoutUrl) {
            const logoutUrl = new URL(`${config.cognitoHostedUiDomain}/logout`);
            logoutUrl.searchParams.set('client_id', config.cognitoClientId);
            logoutUrl.searchParams.set('logout_uri', config.logoutUrl);
            window.location.href = logoutUrl.toString();
        } else {
            window.location.href = 'index.html';
        }
    },

    /**
     * Build Cognito Hosted UI login URL
     */
    getLoginUrl(returnPath) {
        const config = window.LIMS_CONFIG;
        const state = returnPath || 'samples.html';

        const loginUrl = new URL(`${config.cognitoHostedUiDomain}/oauth2/authorize`);
        loginUrl.searchParams.set('client_id', config.cognitoClientId);
        loginUrl.searchParams.set('response_type', 'code');
        loginUrl.searchParams.set('scope', 'openid email profile');
        loginUrl.searchParams.set('redirect_uri', config.callbackUrl);
        loginUrl.searchParams.set('state', state);

        return loginUrl.toString();
    },

    /**
     * Require authentication - redirect to login if not authenticated
     */
    requireAuth() {
        const config = window.LIMS_CONFIG;

        // Skip auth check in local dev mode
        if (!config || !config.cognitoHostedUiDomain) {
            return true;
        }

        if (!this.isAuthenticated()) {
            this._redirectToLogin();
            return false;
        }
        return true;
    },

    /**
     * Require specific role - redirect if not authorized
     */
    requireRole(role) {
        if (!this.requireAuth()) return false;

        if (!this.hasRole(role)) {
            window.location.href = 'samples.html';
            return false;
        }
        return true;
    },

    /**
     * Attempt to refresh tokens using refresh_token
     */
    async refreshTokens() {
        const refreshToken = sessionStorage.getItem(this.STORAGE_KEYS.REFRESH_TOKEN);
        if (!refreshToken) return false;

        const config = window.LIMS_CONFIG;
        if (!config || !config.cognitoHostedUiDomain) return false;

        const tokenUrl = `${config.cognitoHostedUiDomain}/oauth2/token`;

        try {
            const body = new URLSearchParams({
                grant_type: 'refresh_token',
                client_id: config.cognitoClientId,
                refresh_token: refreshToken
            });

            const response = await fetch(tokenUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: body.toString()
            });

            if (!response.ok) return false;

            const tokens = await response.json();
            sessionStorage.setItem(this.STORAGE_KEYS.ID_TOKEN, tokens.id_token);
            sessionStorage.setItem(this.STORAGE_KEYS.ACCESS_TOKEN, tokens.access_token);

            // Clear cached user info
            sessionStorage.removeItem(this.STORAGE_KEYS.USER_INFO);

            return true;
        } catch (e) {
            console.error('Token refresh failed:', e);
            return false;
        }
    },

    // Private methods

    _decodeJwt(token) {
        const parts = token.split('.');
        if (parts.length !== 3) throw new Error('Invalid JWT format');

        const payload = parts[1];
        // Handle base64url encoding
        const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
        const padded = base64 + '='.repeat((4 - base64.length % 4) % 4);
        const decoded = atob(padded);

        return JSON.parse(decoded);
    },

    _isTokenExpired(token) {
        try {
            const payload = this._decodeJwt(token);
            const now = Math.floor(Date.now() / 1000);
            // Add 60 second buffer for clock skew
            return payload.exp < (now + 60);
        } catch (e) {
            return true;
        }
    },

    _redirectToLogin(returnPath) {
        const config = window.LIMS_CONFIG;
        if (!config || !config.cognitoHostedUiDomain) {
            console.error('Cognito not configured');
            return;
        }

        const path = returnPath || window.location.pathname.split('/').pop() || 'samples.html';
        sessionStorage.setItem(this.STORAGE_KEYS.RETURN_PATH, path);
        window.location.href = this.getLoginUrl(path);
    }
};
