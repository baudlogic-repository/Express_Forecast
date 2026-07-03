document.addEventListener('DOMContentLoaded', () => {
    const btnRun = document.getElementById('btn-run');
    const btnExport = document.getElementById('btn-export');
    const loadingOverlay = document.getElementById('loading-overlay');
    const mainContent = document.getElementById('main-content');
    
    let currentExcelBase64 = null;
    let accuracyChart = null;
    let ropChart = null;
    let fullInventory = [];
    let ropHistoryData = [];
    let currentOptimizerVendor = "";
    let currentOptimizerPO = 0;

    // Tab Switching Logic
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active from all
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // Add active to clicked
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // Helper to render table
    function renderTable(tableId, dataArray) {
        if (tableId === 'table-accuracy') {
            const countEl = document.getElementById('accuracy-count');
            if(countEl) countEl.textContent = `Showing ${dataArray ? dataArray.length : 0} items`;
        }
        if (tableId === 'table-deadstock') {
            const countEl = document.getElementById('deadstock-count');
            if(countEl) countEl.textContent = `Showing ${dataArray ? dataArray.length : 0} items`;
        }

        const table = document.getElementById(tableId);
        const thead = table.querySelector('thead');
        const tbody = table.querySelector('tbody');
        
        thead.innerHTML = '';
        tbody.innerHTML = '';
        
        if (!dataArray || dataArray.length === 0) {
            tbody.innerHTML = '<tr><td>No data available.</td></tr>';
            return;
        }

        // Headers
        const headers = Object.keys(dataArray[0]);
        const trHead = document.createElement('tr');
        headers.forEach(h => {
            const th = document.createElement('th');
            th.textContent = h;
            trHead.appendChild(th);
        });
        
        if (tableId === 'table-vendor') {
            const th = document.createElement('th');
            th.textContent = 'Action';
            trHead.appendChild(th);
        }
        
        thead.appendChild(trHead);

        // Rows
        dataArray.forEach(row => {
            const tr = document.createElement('tr');
            headers.forEach(h => {
                const td = document.createElement('td');
                let val = row[h];
                if (typeof val === 'number') {
                    if (h.toLowerCase().includes('cost') || h.toLowerCase().includes('value') || h.toLowerCase().includes('capital')) {
                        val = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
                    }
                }
                if (h === 'Confidence') {
                    const badge = document.createElement('span');
                    badge.textContent = val || 'N/A';
                    badge.style.padding = '3px 8px';
                    badge.style.borderRadius = '12px';
                    badge.style.fontSize = '0.8rem';
                    badge.style.fontWeight = '600';
                    if (val === 'High') {
                        badge.style.backgroundColor = '#dcfce7';
                        badge.style.color = '#166534';
                    } else if (val === 'Medium') {
                        badge.style.backgroundColor = '#fef08a';
                        badge.style.color = '#854d0e';
                    } else {
                        badge.style.backgroundColor = '#fee2e2';
                        badge.style.color = '#991b1b';
                    }
                    td.appendChild(badge);
                } else {
                    td.textContent = val;
                }
                
                if (h.toLowerCase().includes('variance')) {
                    if (val > 0) td.style.color = '#ef4444'; 
                    else if (val < 0) td.style.color = '#3b82f6'; 
                    else if (val === 0) td.style.color = '#10b981';
                }
                tr.appendChild(td);
            });
            
            if (tableId === 'table-vendor') {
                const td = document.createElement('td');
                const btn = document.createElement('button');
                btn.className = 'btn-secondary';
                btn.textContent = 'Optimize Order';
                btn.style.padding = '5px 10px';
                btn.style.fontSize = '0.8rem';
                btn.onclick = () => openOptimizerModal(row['Vendor'], row['Total PO Value']);
                td.appendChild(btn);
                tr.appendChild(td);
            }
            
            if (tableId === 'table-accuracy') {
                tr.style.cursor = 'pointer';
                tr.onclick = () => openAccuracyModal(row['Part Number']);
            }
            
            tbody.appendChild(tr);
        });
    }

    // Run Forecast
    btnRun.addEventListener('click', async () => {
        btnRun.disabled = true;
        btnRun.textContent = "Processing...";
        btnExport.disabled = true;
        mainContent.style.display = 'none';
        loadingOverlay.style.display = 'flex';

        try {
            const response = await fetch('/api/forecast', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ connection_string: "" })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Unknown error occurred');
            }

            const result = await response.json();
            
            if (result.status === 'success') {
                fullInventory = result.data.full_inventory || [];
                
                renderTable('table-line', result.data.line_details);
                renderTable('table-ds', result.data.ds_suggestions);
                renderTable('table-forecast', result.data.ai_forecast);
                renderTable('table-accuracy', result.data.ai_accuracy);
                renderTable('table-vendor', result.data.vendor_summary);
                renderTable('table-deadstock', result.data.dead_stock_radar);
                
                if (result.data.chart_data && result.data.chart_data.length > 0) {
                    renderAccuracyChart(result.data.chart_data);
                }
                
                currentExcelBase64 = result.excel_base64;
                btnExport.disabled = false;
                
                loadingOverlay.style.display = 'none';
                mainContent.style.display = 'block';
                
                // Re-fetch ROPs so any newly saved ROPs are available
                fetchRopHistory();
                
                // Set up accuracy search listener
                setupAccuracySearch(result.data.ai_accuracy);
            }
        } catch (err) {
            alert("Failed to generate forecast: " + err.message);
            loadingOverlay.style.display = 'none';
        } finally {
            btnRun.disabled = false;
            btnRun.textContent = "Generate Forecast";
        }
    });

    // Export to Excel
    btnExport.addEventListener('click', () => {
        if (!currentExcelBase64) return;
        const byteCharacters = atob(currentExcelBase64);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const dateStr = new Date().toISOString().slice(0,10).replace(/-/g,"");
        a.download = `Inventory_Forecast_${dateStr}.xlsx`;
        document.body.appendChild(a);
        a.click();
        
        setTimeout(() => {
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }, 100);
    });

    function renderAccuracyChart(chartData) {
        const ctx = document.getElementById('accuracyChart').getContext('2d');
        if (accuracyChart) accuracyChart.destroy();
        
        const labels = chartData.map(d => d.month);
        const forecastData = chartData.map(d => d.total_forecast);
        const actualData = chartData.map(d => d.total_actual);
        
        accuracyChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    { label: 'AI Forecast', data: forecastData, borderColor: '#C3002F', backgroundColor: 'rgba(195, 0, 47, 0.1)', borderWidth: 2, tension: 0.4, fill: true },
                    { label: 'Actual Sales', data: actualData, borderColor: '#333333', backgroundColor: 'rgba(51, 51, 51, 0.1)', borderWidth: 2, tension: 0.4, fill: true }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#333333', font: { family: 'Open Sans' } } }, tooltip: { mode: 'index', intersect: false } },
                scales: {
                    x: { ticks: { color: '#64748b' }, grid: { color: 'rgba(0,0,0,0.05)' } },
                    y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(0,0,0,0.05)' }, beginAtZero: true }
                }
            }
        });
    }

    let partAccuracyChart;
    
    async function openAccuracyModal(partNo) {
        document.getElementById('modal-accuracy-title').textContent = `Accuracy History: ${partNo}`;
        document.getElementById('accuracy-modal').style.display = 'flex';
        
        try {
            const res = await fetch(`/api/accuracy/${encodeURIComponent(partNo)}`);
            const result = await res.json();
            
            if (result.status === 'success') {
                const ctx = document.getElementById('partAccuracyChart').getContext('2d');
                if (partAccuracyChart) partAccuracyChart.destroy();
                
                const labels = result.data.map(d => d.month);
                const forecastData = result.data.map(d => d.predicted);
                const actualData = result.data.map(d => d.actual);
                
                partAccuracyChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [
                            { label: 'AI Forecast', data: forecastData, borderColor: '#C3002F', borderDash: [5, 5], backgroundColor: 'transparent', borderWidth: 2, tension: 0.4 },
                            { label: 'Actual Sales', data: actualData, borderColor: '#333333', backgroundColor: 'rgba(51, 51, 51, 0.1)', borderWidth: 3, tension: 0.4, fill: true }
                        ]
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false,
                        plugins: { legend: { labels: { color: '#333333', font: { family: 'Open Sans' } } }, tooltip: { mode: 'index', intersect: false } },
                        scales: {
                            x: { ticks: { color: '#64748b' }, grid: { color: 'rgba(0,0,0,0.05)' } },
                            y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(0,0,0,0.05)' }, beginAtZero: true }
                        }
                    }
                });
            }
        } catch (e) { 
            console.error("Error fetching part accuracy", e); 
            alert("Failed to load historical accuracy for this part.");
        }
    }
    
    document.getElementById('modal-accuracy-close').addEventListener('click', () => {
        document.getElementById('accuracy-modal').style.display = 'none';
    });
    
    function setupAccuracySearch(accuracyData) {
        const searchInput = document.getElementById('accuracy-search');
        if (!searchInput) return;
        
        // Remove old listeners by replacing node
        const newSearch = searchInput.cloneNode(true);
        searchInput.parentNode.replaceChild(newSearch, searchInput);
        
        newSearch.addEventListener('input', (e) => {
            const term = e.target.value.toLowerCase();
            const filtered = accuracyData.filter(row => 
                String(row['Part Number']).toLowerCase().includes(term) ||
                String(row['Description']).toLowerCase().includes(term)
            );
            renderTable('table-accuracy', filtered);
        });
    }

    // ==========================================
    // ROP HISTORY LOGIC
    // ==========================================
    async function fetchRopHistory() {
        try {
            const res = await fetch('/api/rops');
            const result = await res.json();
            if(result.status === 'success') {
                ropHistoryData = result.data;
                const parts = [...new Set(ropHistoryData.map(d => d.part_no))];
                renderRopPartsList(parts);
            }
        } catch(e) { 
            console.error("Error fetching ROPs", e); 
            // Silent fail for ROP history as it's non-critical to core flow
        }
    }

    function renderRopPartsList(parts) {
        const tbody = document.querySelector('#table-rop-parts tbody');
        tbody.innerHTML = '';
        parts.forEach(p => {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.textContent = p;
            tr.appendChild(td);
            tr.onclick = () => renderRopChart(p);
            tbody.appendChild(tr);
        });
    }
    
    document.getElementById('rop-search').addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const parts = [...new Set(ropHistoryData.map(d => d.part_no))];
        const filtered = parts.filter(p => String(p).toLowerCase().includes(term));
        renderRopPartsList(filtered);
    });

    function renderRopChart(partNo) {
        const partData = ropHistoryData.filter(d => d.part_no === partNo);
        const labels = partData.map(d => d.run_date);
        const ropVals = partData.map(d => d.suggested_rop);
        
        const ctx = document.getElementById('ropChart').getContext('2d');
        if (ropChart) ropChart.destroy();
        
        ropChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: `Suggested ROP for ${partNo}`,
                    data: ropVals,
                    borderColor: '#C3002F',
                    backgroundColor: 'rgba(195, 0, 47, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { y: { beginAtZero: true } }
            }
        });
    }
    
    // Fetch ROPs on initial load
    fetchRopHistory();

    // ==========================================
    // FREIGHT OPTIMIZER LOGIC
    // ==========================================
    const modal = document.getElementById('optimizer-modal');
    const modalClose = document.getElementById('modal-close');
    const btnOptimize = document.getElementById('btn-optimize');

    modalClose.onclick = () => modal.style.display = 'none';

    function openOptimizerModal(vendorName, currentPo) {
        currentOptimizerVendor = vendorName;
        currentOptimizerPO = currentPo;
        
        document.getElementById('modal-vendor-name').textContent = `Vendor Optimization: ${vendorName}`;
        document.getElementById('modal-current-po').textContent = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(currentPo);
        document.getElementById('modal-target-amount').value = Math.ceil(currentPo / 100) * 100; // Round up to nearest 100
        
        document.querySelector('#table-optimizer tbody').innerHTML = '';
        document.getElementById('modal-new-po').textContent = '$0.00';
        
        modal.style.display = 'flex';
    }

    btnOptimize.onclick = () => {
        let targetAmount = parseFloat(document.getElementById('modal-target-amount').value);
        if (isNaN(targetAmount) || targetAmount <= currentOptimizerPO) {
            alert("Target amount must be greater than current PO.");
            return;
        }
        
        let gap = targetAmount - currentOptimizerPO;
        let addedCost = 0;
        
        // 1. Filter inventory for this vendor, un-ordered parts only
        let candidates = fullInventory.filter(item => 
            item['Vendor Name'] === currentOptimizerVendor && 
            (item['Suggested_Order_Qty'] === 0 || !item['Suggested_Order_Qty']) &&
            (item['pi_cost'] && item['pi_cost'] > 0)
        );
        
        // 2. Calculate surplus
        candidates.forEach(item => {
            let available = item['Total_Available'] || 0;
            let rop = item['Reorder_Point'] || 0;
            item._surplus = available - rop;
        });
        
        // 3. Sort by surplus ASC (closest to needing an order)
        candidates.sort((a, b) => a._surplus - b._surplus);
        
        const tbody = document.querySelector('#table-optimizer tbody');
        tbody.innerHTML = '';
        
        let selectedPartsMap = new Map();
        
        if (candidates.length > 0) {
            let loopGuard = 0;
            while (gap > 0 && loopGuard < 100) {
                let addedInPass = false;
                for (let item of candidates) {
                    if (gap <= 0) break;
                    
                    // Suggest 1 month supply, rounded up to the nearest whole unit
                    let suggestedQty = Math.ceil(item['AI_Forecast_M1']) || 1;
                    if (suggestedQty <= 0) suggestedQty = 1;
                    
                    let cost = item['pi_cost'];
                    let totalLineCost = suggestedQty * cost;
                    
                    if (selectedPartsMap.has(item['pi_part_no'])) {
                        let existing = selectedPartsMap.get(item['pi_part_no']);
                        existing.qty += suggestedQty;
                        existing.lineCost += totalLineCost;
                    } else {
                        selectedPartsMap.set(item['pi_part_no'], {
                            part: item['pi_part_no'],
                            desc: item['pi_description'],
                            surplus: item._surplus,
                            qty: suggestedQty,
                            lineCost: totalLineCost
                        });
                    }
                    
                    gap -= totalLineCost;
                    addedCost += totalLineCost;
                    addedInPass = true;
                }
                if (!addedInPass) break;
                loopGuard++;
            }
        }
        
        let selectedParts = Array.from(selectedPartsMap.values());
        
        selectedParts.forEach(sp => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${sp.part}</td>
                <td>${sp.desc}</td>
                <td>${sp.surplus}</td>
                <td>${sp.qty}</td>
                <td>${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(sp.lineCost)}</td>
            `;
            tbody.appendChild(tr);
        });
        
        if (selectedParts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5">No suitable parts found to top-up.</td></tr>';
        }
        
        let newTotal = currentOptimizerPO + addedCost;
        document.getElementById('modal-new-po').textContent = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(newTotal);
    };
});
