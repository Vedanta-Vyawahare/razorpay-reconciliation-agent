document.addEventListener('DOMContentLoaded', () => {
    
    // State
    let currentPath = 'rzp'; // rzp, ledger, unknown
    let currentData = [];

    // DOM Elements
    const btnRzp = document.getElementById('btn-path-rzp');
    const btnLedger = document.getElementById('btn-path-ledger');
    const btnUnknown = document.getElementById('btn-path-unknown');
    
    const btnDashboard = document.getElementById('btn-dashboard');
    const btnReview = document.getElementById('btn-review');
    const viewDashboard = document.getElementById('view-dashboard');
    const viewReview = document.getElementById('view-review');

    // Navigation Logic
    function setActiveButton(group, activeBtn) {
        group.forEach(btn => btn.classList.remove('active'));
        activeBtn.classList.add('active');
    }

    btnRzp.addEventListener('click', () => {
        setActiveButton([btnRzp, btnLedger, btnUnknown], btnRzp);
        currentPath = 'rzp';
        loadData();
    });

    btnLedger.addEventListener('click', () => {
        setActiveButton([btnRzp, btnLedger, btnUnknown], btnLedger);
        currentPath = 'ledger';
        loadData();
    });

    btnUnknown.addEventListener('click', () => {
        setActiveButton([btnRzp, btnLedger, btnUnknown], btnUnknown);
        currentPath = 'unknown';
        loadData();
    });

    btnDashboard.addEventListener('click', () => {
        setActiveButton([btnDashboard, btnReview], btnDashboard);
        viewDashboard.classList.add('active');
        viewReview.classList.remove('active');
    });

    btnReview.addEventListener('click', () => {
        setActiveButton([btnDashboard, btnReview], btnReview);
        viewReview.classList.add('active');
        viewDashboard.classList.remove('active');
    });

    document.getElementById('status-filter').addEventListener('change', () => {
        renderTable();
    });

    // Data Fetching
    async function loadData() {
        try {
            let endpoint = '';
            if (currentPath === 'rzp') endpoint = '/api/settlements';
            else if (currentPath === 'ledger') endpoint = '/api/ledger';
            else endpoint = '/api/unknown_bank';

            const res = await fetch(endpoint);
            currentData = await res.json();
            
            updateStats();
            setupTableHeaders();
            renderTable();
            renderReviewQueue(currentData.filter(s => s.status === 'REVIEW' || currentPath === 'unknown'));
            
            document.getElementById('table-title').innerText = 
                currentPath === 'rzp' ? 'Razorpay Reconciliation' : 
                currentPath === 'ledger' ? 'Ledger Reconciliation' : 'Unknown Bank Rows';
                
        } catch (e) {
            console.error("Error loading data:", e);
        }
    }

    function updateStats() {
        if (currentPath === 'unknown') {
            document.getElementById('stat-total-title').innerText = 'Unknown Rows';
            document.getElementById('stat-total').innerText = currentData.length;
            document.getElementById('stat-matched').innerText = '--';
            document.getElementById('stat-review').innerText = currentData.length;
            document.getElementById('stat-unmatched').innerText = '--';
            return;
        }

        document.getElementById('stat-total-title').innerText = 'Total Rows';
        document.getElementById('stat-total').innerText = currentData.length;
        document.getElementById('stat-matched').innerText = currentData.filter(d => d.status === 'MATCHED').length;
        document.getElementById('stat-review').innerText = currentData.filter(d => d.status === 'REVIEW').length;
        document.getElementById('stat-unmatched').innerText = currentData.filter(d => d.status === 'UNMATCHED').length;
    }

    function getBadgeClass(status) {
        if(status === 'MATCHED') return 'matched';
        if(status === 'REVIEW') return 'review';
        return 'unmatched';
    }

    function setupTableHeaders() {
        const tr = document.getElementById('table-head-row');
        if (currentPath === 'rzp') {
            tr.innerHTML = `
                <th>ID</th>
                <th>Date</th>
                <th>Amount</th>
                <th>Bank Ref</th>
                <th>Score</th>
                <th>Status</th>
                <th>Actions</th>
            `;
        } else if (currentPath === 'ledger') {
            tr.innerHTML = `
                <th>Ledger ID</th>
                <th>Invoice</th>
                <th>Amount</th>
                <th>Customer</th>
                <th>Score</th>
                <th>Status</th>
                <th>Actions</th>
            `;
        } else {
            tr.innerHTML = `
                <th>Bank Date</th>
                <th>Amount</th>
                <th>Narration</th>
                <th>Reference</th>
                <th>Source Reason</th>
            `;
        }
    }

    function detectMismatches(item) {
        const mismatches = [];
        if (currentPath === 'rzp') {
            if (item.amount_score < 40) mismatches.push('Amount Mismatch');
            if (item.date_score < 15) mismatches.push('Date Delay');
            if (item.reference_score < 35) mismatches.push('Reference Mismatch');
            if (item.ambiguity_penalty > 0) mismatches.push('Competing Candidates');
        } else if (currentPath === 'ledger') {
            // Ledger path: reference is NOT applicable — do not flag it
            if (item.amount_score < 45) mismatches.push('Amount Mismatch');
            if (item.date_score < 25) mismatches.push('Date Delay');
            if (item.party_score != null && item.party_score < 10) mismatches.push('Party Name Mismatch');
            if (item.ambiguity_penalty > 0) mismatches.push('Competing Candidates');
        }
        return mismatches;
    }

    function renderMismatchesHtml(mismatches) {
        if (mismatches.length === 0) return '';
        return `<div class="mismatch-tags">` + mismatches.map(m => `<span class="badge mismatch">${m}</span>`).join('') + `</div>`;
    }

    function renderTable() {
        const statusFilter = document.getElementById('status-filter').value;
        const tbody = document.getElementById('table-body');
        tbody.innerHTML = '';
        
        let displayData = currentData;
        if (statusFilter && currentPath !== 'unknown') {
            displayData = currentData.filter(d => d.status === statusFilter);
        }

        displayData.forEach(item => {
            const tr = document.createElement('tr');
            
            if (currentPath === 'rzp') {
                tr.innerHTML = `
                    <td><strong>${item.settlement_id}</strong></td>
                    <td>${item.settlement_date}</td>
                    <td>₹${parseFloat(item.razorpay_net_settlement).toLocaleString()}</td>
                    <td>${item.bank_reference || '-'}</td>
                    <td>${item.confidence}%</td>
                    <td><span class="badge ${getBadgeClass(item.status)}">${item.status}</span></td>
                    <td><button class="action-btn" onclick="openDetails('${item.settlement_id}', 'rzp')">View</button></td>
                `;
            } else if (currentPath === 'ledger') {
                tr.innerHTML = `
                    <td><strong>${item.ledger_id}</strong></td>
                    <td>${item.invoice_id}</td>
                    <td>₹${parseFloat(item.ledger_amount).toLocaleString()}</td>
                    <td>${item.customer_name}</td>
                    <td>${item.confidence}%</td>
                    <td><span class="badge ${getBadgeClass(item.status)}">${item.status}</span></td>
                    <td><button class="action-btn" onclick="openDetails('${item.ledger_id}', 'ledger')">View</button></td>
                `;
            } else {
                tr.innerHTML = `
                    <td>${item.value_date || '-'}</td>
                    <td>₹${parseFloat(item.credit || 0).toLocaleString()}</td>
                    <td>${item.narration || '-'}</td>
                    <td>${item.ref_no_cheque_no || '-'}</td>
                    <td><span style="font-size: 0.85rem; color: var(--text-secondary);">${item.source_reason || '-'}</span></td>
                `;
            }
            tbody.appendChild(tr);
        });
    }

    function renderReviewQueue(reviews) {
        const queue = document.getElementById('review-list');
        queue.innerHTML = '';
        
        if (currentPath === 'unknown') {
             queue.innerHTML = `<div class="glass-panel" style="padding: 2rem; color: var(--text-secondary);">Unknown rows are not reconciled automatically. Please map them manually via your ERP.</div>`;
             return;
        }
        
        if(reviews.length === 0) {
            queue.innerHTML = `<div class="glass-panel" style="padding: 2rem; text-align:center; color: var(--text-secondary);">No reviews pending in this path. Great job!</div>`;
            return;
        }

        reviews.forEach(item => {
            const id = currentPath === 'rzp' ? item.settlement_id : item.ledger_id;
            const expectedAmt = currentPath === 'rzp' ? item.razorpay_net_settlement : item.ledger_amount;
            const expectedDate = currentPath === 'rzp' ? item.settlement_date : item.ledger_date;
            
            const mismatches = detectMismatches(item);
            
            const card = document.createElement('div');
            card.className = 'review-card glass-panel';
            card.innerHTML = `
                <div class="review-card-header">
                    <div>
                        <h3>ID: ${id}</h3>
                        <p style="color: var(--text-secondary); font-size: 0.9rem;">Exp. Amount: ₹${expectedAmt} | Date: ${expectedDate}</p>
                    </div>
                    <span class="badge review">${item.confidence}% Confidence</span>
                </div>
                ${renderMismatchesHtml(mismatches)}
                <div class="llm-reasoning" style="margin-top: 1rem;">
                    <strong>Engine Reason:</strong> ${item.reason}
                    <br><br>
                    <strong>Evidence Breakdown:</strong> ${item.score_explanation}
                </div>
                <div class="candidate-options">
                    <button class="override-btn" onclick="submitOverride('${id}', '${item.bank_reference || ''}', '${currentPath}')">Accept Top Candidate (${item.bank_reference || 'N/A'})</button>
                    <button class="override-btn" style="color:var(--danger); border-color:var(--danger);" onclick="submitOverride('${id}', 'NONE', '${currentPath}')">Mark Unmatched</button>
                </div>
            `;
            queue.appendChild(card);
        });
    }

    window.submitOverride = async function(id, bank_reference, pathType) {
        if (pathType === 'ledger') {
            alert("Ledger override endpoint not yet connected in API. (Coming soon)");
            return;
        }
        const reason = prompt("Enter reason for manual override:");
        if (reason === null) return;
        
        try {
            const res = await fetch(`/api/settlements/${id}/override`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    settlement_id: id,
                    bank_reference,
                    reason: reason || "Manual Override via UI",
                    user: "Accountant"
                })
            });
            const data = await res.json();
            alert(data.message);
            loadData();
        } catch (e) {
            alert("Error saving override.");
        }
    };

    // Modal logic
    const modal = document.getElementById('detail-modal');
    const closeBtn = document.querySelector('.close-btn');
    closeBtn.onclick = () => modal.style.display = "none";
    window.onclick = (e) => { if (e.target == modal) modal.style.display = "none"; };

    window.openDetails = function(id, pathType) {
        const idField = pathType === 'rzp' ? 'settlement_id' : 'ledger_id';
        const item = currentData.find(s => s[idField] === id);
        if(!item) return;

        const mismatches = detectMismatches(item);
        
        const amountField = pathType === 'rzp' ? 'razorpay_net_settlement' : 'ledger_amount';
        const dateField = pathType === 'rzp' ? 'settlement_date' : 'ledger_date';

        document.getElementById('modal-title').innerText = `Details: ${id}`;
        document.getElementById('modal-body').innerHTML = `
            <div class="badge ${getBadgeClass(item.status)}" style="display:inline-block; margin-bottom:1rem;">${item.status} - ${item.confidence}%</div>
            <div style="margin-bottom: 1rem;">${renderMismatchesHtml(mismatches)}</div>
            <div class="llm-reasoning">${item.reason}</div>
            
            <div class="detail-grid">
                <div class="detail-item"><strong>Date</strong> ${item[dateField]}</div>
                <div class="detail-item"><strong>Expected Amount</strong> ₹${item[amountField]}</div>
                <div class="detail-item"><strong>Bank Ref</strong> ${item.bank_reference || 'N/A'}</div>
                <div class="detail-item"><strong>Bank Credit</strong> ₹${item.bank_credit || item.bank_amount || '0'}</div>
                <div class="detail-item"><strong>Bank Date</strong> ${item.bank_date || 'N/A'}</div>
            </div>
            
            <h3 style="margin-top: 1.5rem; margin-bottom:0.5rem; font-size:1rem;">Evidence Scores</h3>
            <div class="detail-grid" style="grid-template-columns: 1fr 1fr 1fr 1fr; margin-top: 0.5rem;">
                <div class="detail-item"><strong>Amount</strong> ${item.amount_score}</div>
                <div class="detail-item"><strong>Date</strong> ${item.date_score}</div>
                ${pathType === 'rzp' 
                    ? `<div class="detail-item"><strong>Reference</strong> ${item.reference_score}</div>` 
                    : `<div class="detail-item"><strong>Reference</strong> <span style="color:var(--text-secondary); font-style:italic;">N/A</span></div>`}
                <div class="detail-item"><strong>Type</strong> ${item.transaction_type_score || 0}</div>
                <div class="detail-item"><strong>Narration</strong> ${item.narration_score || 0}</div>
                ${pathType === 'ledger' ? `<div class="detail-item"><strong>Party</strong> ${item.party_score || 0}</div>` : ''}
            </div>
            
            <p style="margin-top: 1.5rem; color:var(--text-secondary); font-size: 0.9rem;">${item.score_explanation}</p>
        `;
        modal.style.display = "block";
    };

    // Init
    loadData();
});
