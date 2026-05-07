class AIAssist {
    constructor() {
        this.modal = null;
        this.isLoading = false;
        this.init();
    }

    init() {
        this.createModal();
        this.attachEventListeners();
    }

    createModal() {
        const html = `
            <div id="ai-assist-modal" class="ai-assist-modal hidden">
                <div class="ai-assist-overlay"></div>
                <div class="ai-assist-panel">
                    <div class="ai-assist-header">
                        <h2>🤖 AI Civilian Generator</h2>
                        <button class="ai-assist-close">&times;</button>
                    </div>

                    <div class="ai-assist-content">
                        <div class="ai-assist-section">
                            <label>Gender</label>
                            <select id="ai-gender" class="ai-input">
                                <option value="random">Random</option>
                                <option value="male">Male</option>
                                <option value="female">Female</option>
                            </select>
                        </div>

                        <div class="ai-assist-section">
                            <label>Ethnicity</label>
                            <select id="ai-ethnicity" class="ai-input">
                                <option value="random">Random</option>
                                <option value="African American">African American</option>
                                <option value="Hispanic/Latino">Hispanic/Latino</option>
                                <option value="Caucasian">Caucasian</option>
                                <option value="Asian">Asian</option>
                                <option value="Middle Eastern">Middle Eastern</option>
                                <option value="Mixed">Mixed</option>
                            </select>
                        </div>

                        <div class="ai-assist-section">
                            <label>Gang Affiliation</label>
                            <select id="ai-gang" class="ai-input">
                                <option value="None">None</option>
                                <option value="Grove Street Families">Grove Street Families</option>
                                <option value="Ballas">Ballas</option>
                                <option value="Vagos">Vagos</option>
                                <option value="Mafia">Mafia</option>
                                <option value="Triads">Triads</option>
                                <option value="Bikers">Bikers</option>
                            </select>
                        </div>

                        <div class="ai-assist-section">
                            <label>Risk Level</label>
                            <select id="ai-risk" class="ai-input">
                                <option value="Low">Low</option>
                                <option value="Medium">Medium</option>
                                <option value="High">High</option>
                                <option value="Critical">Critical</option>
                            </select>
                        </div>

                        <div class="ai-assist-section">
                            <label>Occupation Type</label>
                            <select id="ai-occupation" class="ai-input">
                                <option value="random">Random</option>
                                <option value="Construction Worker">Construction Worker</option>
                                <option value="Mechanic">Mechanic</option>
                                <option value="Security Guard">Security Guard</option>
                                <option value="Bartender">Bartender</option>
                                <option value="Taxi Driver">Taxi Driver</option>
                                <option value="Drug Dealer">Drug Dealer</option>
                                <option value="Unemployed">Unemployed</option>
                            </select>
                        </div>

                        <div class="ai-assist-section">
                            <label>Neighborhood</label>
                            <select id="ai-neighborhood" class="ai-input">
                                <option value="random">Random</option>
                                <option value="Grove Street">Grove Street</option>
                                <option value="Downtown">Downtown</option>
                                <option value="Vinewood">Vinewood</option>
                                <option value="Del Perro">Del Perro</option>
                                <option value="Sandy Shores">Sandy Shores</option>
                            </select>
                        </div>

                        <div class="ai-assist-section">
                            <label>Criminal History Level</label>
                            <select id="ai-criminal" class="ai-input">
                                <option value="low">Clean Record</option>
                                <option value="medium">Minor Offenses</option>
                                <option value="high">Extensive History</option>
                            </select>
                        </div>

                        <button id="ai-randomize-btn" class="ai-button secondary">
                            🎲 Randomize Everything
                        </button>
                    </div>

                    <div class="ai-assist-footer">
                        <button id="ai-cancel-btn" class="ai-button secondary">Cancel</button>
                        <button id="ai-generate-btn" class="ai-button primary">
                            ✨ Generate Civilian
                        </button>
                    </div>

                    <div id="ai-loading" class="ai-loading hidden">
                        <div class="ai-spinner"></div>
                        <p>Generating realistic civilian...</p>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);
        this.modal = document.getElementById('ai-assist-modal');
    }

    attachEventListeners() {
        // Open modal
        const aiAssistBtn = document.getElementById('ai-assist-btn');
        if (aiAssistBtn) {
            aiAssistBtn.addEventListener('click', () => this.openModal());
        }

        // Close modal
        this.modal.querySelector('.ai-assist-close').addEventListener('click', () => this.closeModal());
        document.getElementById('ai-cancel-btn').addEventListener('click', () => this.closeModal());
        this.modal.querySelector('.ai-assist-overlay').addEventListener('click', () => this.closeModal());

        // Generate
        document.getElementById('ai-generate-btn').addEventListener('click', () => this.generate());

        // Randomize
        document.getElementById('ai-randomize-btn').addEventListener('click', () => this.randomizeAll());
    }

    openModal() {
        this.modal.classList.remove('hidden');
    }

    closeModal() {
        this.modal.classList.add('hidden');
    }

    randomizeAll() {
        const selects = ['ai-gender', 'ai-ethnicity', 'ai-gang', 'ai-risk', 'ai-occupation', 'ai-neighborhood', 'ai-criminal'];
        selects.forEach(id => {
            const select = document.getElementById(id);
            const options = select.querySelectorAll('option');
            const randomIndex = Math.floor(Math.random() * options.length);
            select.selectedIndex = randomIndex;
        });
    }

    async generate() {
        if (this.isLoading) return;

        this.isLoading = true;
        document.getElementById('ai-loading').classList.remove('hidden');
        document.getElementById('ai-generate-btn').disabled = true;

        try {
            const params = {
                gender: document.getElementById('ai-gender').value,
                ethnicity: document.getElementById('ai-ethnicity').value,
                gang_affiliation: document.getElementById('ai-gang').value,
                risk_level: document.getElementById('ai-risk').value,
                occupation_type: document.getElementById('ai-occupation').value,
                neighborhood: document.getElementById('ai-neighborhood').value,
                criminal_history_level: document.getElementById('ai-criminal').value,
            };

            const response = await fetch('/api/ai/civilian-assist', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params),
            });

            const result = await response.json();

            if (result.success) {
                this.autofillForm(result.data);
                this.closeModal();
            } else {
                this.showToast(`❌ Generation failed: ${result.error}`, 'error');
            }
        } catch (error) {
            this.showToast(`❌ Error: ${error.message}`, 'error');
        } finally {
            this.isLoading = false;
            document.getElementById('ai-loading').classList.add('hidden');
            document.getElementById('ai-generate-btn').disabled = false;
        }
    }

    autofillForm(data) {
        // Map API response keys to form field name attributes
        const fieldMap = {
            'first_name': 'firstName',
            'last_name': 'lastName',
            'date_of_birth': 'dob',
            'gender': 'gender',
            'phone_number': 'phone',
            'address': 'address',
            'occupation': 'occupation',
            'gang_affiliation': 'faction',
            'biography': 'backstory',
            'criminal_background': 'background',
        };

        for (const [dataKey, fieldName] of Object.entries(fieldMap)) {
            const value = data[dataKey];
            if (!value) continue;

            // Try by name attribute first (civilian.html uses name=)
            const input = document.querySelector(`[name="${fieldName}"]`);
            if (input) {
                input.value = value;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }

        this.showToast('✨ All fields auto-filled!', 'success');
    }

    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('show');
        }, 10);

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.aiAssist = new AIAssist();
});
