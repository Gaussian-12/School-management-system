// Global variables
let students = [];
let currentGrades = {};
let currentSubject = 'Mathematics';

// DOM elements
const gradesTableBody = document.getElementById('gradesTableBody');
const subjectSelect = document.getElementById('subjectSelect');
const saveAllBtn = document.getElementById('saveAllBtn');
const refreshBtn = document.getElementById('refreshBtn');
const voiceBtn = document.getElementById('voiceBtn');
const voiceStatus = document.getElementById('voiceStatus');
const reportStudentSelect = document.getElementById('reportStudentSelect');
const generateReportBtn = document.getElementById('generateReportBtn');

// Load students on page load
async function loadStudents() {
    try {
        const response = await fetch('/api/students');
        students = await response.json();
        
        // Populate student selects
        reportStudentSelect.innerHTML = '<option value="">Select Student</option>';
        students.forEach(student => {
            const option = document.createElement('option');
            option.value = student.id;
            option.textContent = `${student.name} (${student.class})`;
            reportStudentSelect.appendChild(option);
        });
        
        // Load grades for all students
        await loadGrades();
    } catch (error) {
        console.error('Error loading students:', error);
        gradesTableBody.innerHTML = '<tr><td colspan="3">Error loading students</td></tr>';
    }
}

// Load grades
async function loadGrades() {
    try {
        // For now, just show students with empty grades
        gradesTableBody.innerHTML = '';
        students.forEach(student => {
            const row = document.createElement('tr');
            row.dataset.studentId = student.id;
            
            // Student name cell
            const nameCell = document.createElement('td');
            nameCell.textContent = student.name;
            row.appendChild(nameCell);
            
            // Grade input cell
            const gradeCell = document.createElement('td');
            const gradeInput = document.createElement('input');
            gradeInput.type = 'number';
            gradeInput.min = 0;
            gradeInput.max = 100;
            gradeInput.className = 'grade-input';
            gradeInput.placeholder = 'Enter grade';
            gradeInput.value = currentGrades[student.id]?.[currentSubject] || '';
            gradeInput.addEventListener('change', () => {
                markAsUnsaved(student.id, gradeInput.value);
            });
            gradeCell.appendChild(gradeInput);
            row.appendChild(gradeCell);
            
            // Status cell
            const statusCell = document.createElement('td');
            const statusSpan = document.createElement('span');
            statusSpan.className = 'status-badge status-pending';
            statusSpan.textContent = 'Not saved';
            statusCell.appendChild(statusSpan);
            row.appendChild(statusCell);
            
            gradesTableBody.appendChild(row);
        });
    } catch (error) {
        console.error('Error loading grades:', error);
    }
}

// Mark grade as unsaved
function markAsUnsaved(studentId, value) {
    if (!currentGrades[studentId]) {
        currentGrades[studentId] = {};
    }
    currentGrades[studentId][currentSubject] = value;
    
    // Update status cell
    const row = document.querySelector(`tr[data-student-id="${studentId}"]`);
    if (row) {
        const statusSpan = row.cells[2].querySelector('span');
        statusSpan.className = 'status-badge status-pending';
        statusSpan.textContent = 'Not saved';
    }
}

// Save all grades
async function saveAllGrades() {
    let savedCount = 0;
    
    for (const studentId in currentGrades) {
        const gradeValue = currentGrades[studentId][currentSubject];
        if (gradeValue !== undefined && gradeValue !== '') {
            try {
                const response = await fetch('/api/grade/manual', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        student_id: parseInt(studentId),
                        subject: currentSubject,
                        grade_value: parseInt(gradeValue)
                    })
                });
                
                if (response.ok) {
                    savedCount++;
                    // Update status
                    const row = document.querySelector(`tr[data-student-id="${studentId}"]`);
                    if (row) {
                        const statusSpan = row.cells[2].querySelector('span');
                        statusSpan.className = 'status-badge status-saved';
                        statusSpan.textContent = 'Saved';
                    }
                }
            } catch (error) {
                console.error(`Error saving grade for student ${studentId}:`, error);
            }
        }
    }
    
    // Clear current grades
    currentGrades = {};
    
    // Show success message
    const statusDiv = document.createElement('div');
    statusDiv.className = 'status status-success';
    statusDiv.textContent = `✅ Saved ${savedCount} grades successfully!`;
    document.querySelector('.section').insertBefore(statusDiv, document.querySelector('.table-container'));
    setTimeout(() => statusDiv.remove(), 3000);
}

// Voice input
function setupVoiceInput() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        voiceStatus.innerHTML = '❌ Voice input not supported in this browser. Use Chrome on a Chromebook.';
        voiceBtn.disabled = true;
        return;
    }
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    
    voiceBtn.addEventListener('click', () => {
        recognition.start();
        voiceStatus.innerHTML = '🎤 Listening... Speak clearly';
        voiceStatus.className = 'status status-listening';
        voiceBtn.disabled = true;
    });
    
    recognition.onresult = (event) => {
        const text = event.results[0][0].transcript;
        voiceStatus.innerHTML = `📝 Heard: "${text}" - Processing...`;
        
        // Parse: "John 85, Maria 92, Ahmed 78"
        const words = text.toLowerCase().split(/[\s,]+/);
        
        let parsedCount = 0;
        for (let i = 0; i < words.length - 1; i += 2) {
            const spokenName = words[i].charAt(0).toUpperCase() + words[i].slice(1);
            const gradeValue = parseInt(words[i + 1]);
            
            if (!isNaN(gradeValue) && gradeValue >= 0 && gradeValue <= 100) {
                // Find matching student
                const student = students.find(s => s.name.toLowerCase().includes(spokenName.toLowerCase()));
                if (student) {
                    // Find the grade input for this student
                    const row = document.querySelector(`tr[data-student-id="${student.id}"]`);
                    if (row) {
                        const gradeInput = row.cells[1].querySelector('input');
                        if (gradeInput) {
                            gradeInput.value = gradeValue;
                            markAsUnsaved(student.id, gradeValue);
                            parsedCount++;
                        }
                    }
                }
            }
        }
        
        voiceStatus.innerHTML = `✅ Added ${parsedCount} grades from voice! Click save to store them.`;
        voiceStatus.className = 'status status-success';
        voiceBtn.disabled = false;
        
        setTimeout(() => {
            voiceStatus.innerHTML = '';
            voiceStatus.className = 'status';
        }, 3000);
    };
    
    recognition.onerror = (event) => {
        voiceStatus.innerHTML = `❌ Error: ${event.error}. Try again.`;
        voiceStatus.className = 'status status-error';
        voiceBtn.disabled = false;
    };
    
    recognition.onend = () => {
        voiceBtn.disabled = false;
    };
}

// Generate report card
async function generateReport() {
    const studentId = reportStudentSelect.value;
    if (!studentId) {
        alert('Please select a student');
        return;
    }
    
    try {
        window.open(`/api/report/${studentId}`, '_blank');
    } catch (error) {
        console.error('Error generating report:', error);
        alert('Error generating report');
    }
}

// Event listeners
subjectSelect.addEventListener('change', (e) => {
    currentSubject = e.target.value;
    loadGrades();
});

saveAllBtn.addEventListener('click', saveAllGrades);
refreshBtn.addEventListener('click', loadGrades);
generateReportBtn.addEventListener('click', generateReport);

// Initialize
setupVoiceInput();
loadStudents();
