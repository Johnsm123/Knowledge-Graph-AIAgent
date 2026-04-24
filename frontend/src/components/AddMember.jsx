import { useState, useEffect } from 'react';
import './AddMember.css';

import { API_BASE } from '../lib/apiBase';

// HEDIS MY2025 chronic condition options — maps to ICD-10 codes in CHRONIC_CONDITION_ICD_MAP.
// Measure triggers: Hypertension→CBP | Diabetes(E08-E13)→GSD/EED/KED/BPD
// Hospice/Palliative→global exclusion all measures | Schizophrenia→SMC/SMD/SSD (future)
const CHRONIC_OPTIONS = [
  'Diabetes (Type 1)',
  'Diabetes (Type 2)',
  'Hypertension',
  'Coronary Artery Disease (CAD)',
  'Congestive Heart Failure (CHF)',
  'COPD',
  'Asthma',
  'Chronic Kidney Disease (CKD)',
  'End-Stage Renal Disease (ESRD)',
  'Depression / Anxiety',
  'Schizophrenia / Psychosis',
  'Cancer (Active)',
  'Acute Myocardial Infarction',
  'Substance Use Disorder (SUD)',
  'Hospice / Palliative Care',
  'Pregnancy',
];

const COUNTRY_STATES = {
  'United States': [
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado',
    'Connecticut', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho',
    'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana',
    'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota',
    'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada',
    'New Hampshire', 'New Jersey', 'New Mexico', 'New York',
    'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon',
    'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
    'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington',
    'West Virginia', 'Wisconsin', 'Wyoming', 'District of Columbia',
    'Puerto Rico', 'Guam', 'U.S. Virgin Islands', 'American Samoa',
    'Northern Mariana Islands',
  ],
  'India': [
    // 28 States
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand',
    'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur',
    'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab', 'Rajasthan',
    'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh',
    'Uttarakhand', 'West Bengal',
    // 8 Union Territories
    'Andaman and Nicobar Islands', 'Chandigarh',
    'Dadra and Nagar Haveli and Daman and Diu', 'Delhi (NCT)',
    'Jammu and Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry',
  ],
  'Canada': [
    'Alberta', 'British Columbia', 'Manitoba', 'New Brunswick',
    'Newfoundland and Labrador', 'Northwest Territories', 'Nova Scotia',
    'Nunavut', 'Ontario', 'Prince Edward Island', 'Quebec', 'Saskatchewan',
    'Yukon',
  ],
  'United Kingdom': [
    'England', 'Northern Ireland', 'Scotland', 'Wales',
  ],
  'Australia': [
    'Australian Capital Territory', 'New South Wales', 'Northern Territory',
    'Queensland', 'South Australia', 'Tasmania', 'Victoria', 'Western Australia',
  ],
  'Mexico': [
    'Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche',
    'Chiapas', 'Chihuahua', 'Coahuila', 'Colima', 'Durango', 'Guanajuato',
    'Guerrero', 'Hidalgo', 'Jalisco', 'Mexico City', 'Mexico State',
    'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca', 'Puebla',
    'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa', 'Sonora',
    'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán', 'Zacatecas',
  ],
  'Philippines': [
    'Abra', 'Agusan del Norte', 'Agusan del Sur', 'Aklan', 'Albay',
    'Antique', 'Apayao', 'Aurora', 'Basilan', 'Bataan', 'Batanes',
    'Batangas', 'Benguet', 'Biliran', 'Bohol', 'Bukidnon', 'Bulacan',
    'Cagayan', 'Camarines Norte', 'Camarines Sur', 'Camiguin', 'Capiz',
    'Catanduanes', 'Cavite', 'Cebu', 'Cotabato', 'Davao de Oro',
    'Davao del Norte', 'Davao del Sur', 'Davao Occidental', 'Davao Oriental',
    'Dinagat Islands', 'Eastern Samar', 'Guimaras', 'Ifugao', 'Ilocos Norte',
    'Ilocos Sur', 'Iloilo', 'Isabela', 'Kalinga', 'La Union', 'Laguna',
    'Lanao del Norte', 'Lanao del Sur', 'Leyte', 'Maguindanao del Norte',
    'Maguindanao del Sur', 'Marinduque', 'Masbate', 'Metro Manila',
    'Misamis Occidental', 'Misamis Oriental', 'Mountain Province',
    'Negros Occidental', 'Negros Oriental', 'Northern Samar', 'Nueva Ecija',
    'Nueva Vizcaya', 'Occidental Mindoro', 'Oriental Mindoro', 'Palawan',
    'Pampanga', 'Pangasinan', 'Quezon', 'Quirino', 'Rizal', 'Romblon',
    'Samar', 'Sarangani', 'Siquijor', 'Sorsogon', 'South Cotabato',
    'Southern Leyte', 'Sultan Kudarat', 'Sulu', 'Surigao del Norte',
    'Surigao del Sur', 'Tarlac', 'Tawi-Tawi', 'Zambales',
    'Zamboanga del Norte', 'Zamboanga del Sur', 'Zamboanga Sibugay',
  ],
  'Germany': [
    'Baden-Württemberg', 'Bavaria', 'Berlin', 'Brandenburg', 'Bremen',
    'Hamburg', 'Hesse', 'Lower Saxony', 'Mecklenburg-Vorpommern',
    'North Rhine-Westphalia', 'Rhineland-Palatinate', 'Saarland',
    'Saxony', 'Saxony-Anhalt', 'Schleswig-Holstein', 'Thuringia',
  ],
  'France': [
    'Auvergne-Rhône-Alpes', 'Bourgogne-Franche-Comté', 'Brittany',
    'Centre-Val de Loire', 'Corsica', 'Grand Est', 'Hauts-de-France',
    'Île-de-France', 'Normandy', 'Nouvelle-Aquitaine', 'Occitanie',
    'Pays de la Loire', 'Provence-Alpes-Côte d\'Azur',
  ],
  'Other': ['N/A'],
};

// Country code mapping for zippopotam.us API
const ZIP_COUNTRY_MAP = {
  'United States': 'us',
  'India': 'in',
  'Canada': 'ca',
  'United Kingdom': 'gb',
  'Australia': 'au',
  'Germany': 'de',
  'France': 'fr',
};

// Curated list of conditions commonly relevant to hereditary risk assessment
// (aligned with HEDIS measures: GSD/EED/KED/BPD, COL, BCS, CCS, CBP, SPC).
const HEREDITARY_CONDITIONS = [
  'Diabetes Type 2', 'Diabetes Type 1', 'Hypertension',
  'Coronary Artery Disease', 'Stroke', 'High Cholesterol',
  'Breast Cancer', 'Colorectal Cancer', 'Prostate Cancer',
  'Ovarian Cancer', 'Lung Cancer',
  'Alzheimer\'s Disease', 'Parkinson\'s Disease',
  'Asthma', 'COPD', 'Thyroid Disease',
  'Kidney Disease', 'Liver Disease',
  'Osteoporosis', 'Rheumatoid Arthritis',
  'Depression', 'Bipolar Disorder', 'Schizophrenia',
  'Sickle Cell Disease', 'Hemophilia',
  'Cystic Fibrosis', 'Huntington\'s Disease',
];

const FAMILY_RELATIONS = [
  'Father', 'Mother',
  'Brother', 'Sister',
  'Son', 'Daughter',
  'Paternal Grandfather', 'Paternal Grandmother',
  'Maternal Grandfather', 'Maternal Grandmother',
  'Paternal Uncle', 'Paternal Aunt',
  'Maternal Uncle', 'Maternal Aunt',
];

const SMOKING_OPTIONS    = ['', 'Never', 'Former', 'Current (Light)', 'Current (Heavy)'];
const ALCOHOL_OPTIONS    = ['', 'None', 'Occasional', 'Regular', 'Heavy'];
const EXERCISE_OPTIONS   = ['', 'Sedentary', 'Light', 'Moderate', 'Active', 'Very Active'];
const DIET_OPTIONS       = ['', 'Balanced', 'Vegetarian', 'Vegan', 'Mediterranean', 'Low-Carb / Keto', 'High-Sodium', 'Irregular'];
const STRESS_OPTIONS     = ['', 'Low', 'Moderate', 'High'];

const LANGUAGES = [
  // English & European (HEDIS standard)
  { group: 'English & European', options: [
    'English', 'Spanish', 'French', 'German', 'Portuguese', 'Italian',
    'Polish', 'Russian', 'Ukrainian',
  ]},
  // East Asian & Southeast Asian
  { group: 'East & Southeast Asian', options: [
    'Chinese (Mandarin)', 'Chinese (Cantonese)', 'Vietnamese',
    'Tagalog / Filipino', 'Korean', 'Japanese', 'Khmer (Cambodian)',
    'Hmong', 'Lao', 'Thai', 'Burmese',
  ]},
  // South Asian — Indian Languages (HEDIS-relevant)
  { group: 'South Asian / Indian Languages', options: [
    'Hindi', 'Bengali', 'Telugu', 'Marathi', 'Tamil', 'Gujarati',
    'Urdu', 'Kannada', 'Odia (Oriya)', 'Malayalam', 'Punjabi',
    'Assamese', 'Maithili', 'Santali', 'Kashmiri', 'Nepali',
    'Sindhi', 'Konkani', 'Dogri', 'Manipuri (Meitei)', 'Bodo',
    'Sanskrit',
  ]},
  // Middle Eastern & African
  { group: 'Middle Eastern & African', options: [
    'Arabic', 'Farsi (Persian)', 'Somali', 'Amharic', 'Swahili',
    'Haitian Creole',
  ]},
  // Other
  { group: 'Other', options: ['Sign Language (ASL)', 'Other'] },
];

function AddMember({ onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    // Identity
    member_id: '',
    name: '',
    dob: '',
    age_str: '',
    gender: 'Male',
    // Contact
    email: '',
    phone: '',
    street_address: '',
    city: '',
    state: '',
    zip_code: '',
    country: 'United States',
    // Demographics
    race: '',
    language: 'English',
    tobacco_use: false,
    // Clinical
    chronic_conditions: [],
    // Insurance & Enrollment
    insurance_type: 'Commercial',
    pcp_id: '',
    plan_id: '',
    enrollment_start: '',
    enrollment_end: '2025-12-31',
    // Lifestyle (all optional)
    lifestyle: {
      bmi: '', height_cm: '', weight_kg: '',
      smoking_status: '', alcohol_use: '',
      exercise_frequency: '', diet_type: '',
      sleep_hours_avg: '', stress_level: '', notes: '',
    },
    // Family / ancestral history
    family_history: [],
    // Medical history
    medical_history: {
      past_conditions: [],
      current_conditions: [],
      surgeries: [],
      allergies: [],
      medications: [],
      immunizations: [],
    },
  });

  const [providers, setProviders]   = useState([]);
  const [plans, setPlans]           = useState([]);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState('');
  const [loadingForm, setLoadingForm] = useState(true);
  const [zipLoading, setZipLoading] = useState(false);
  const [zipStatus, setZipStatus]   = useState('');   // 'ok' | 'error' | ''

  const loadFormData = () => {
    setLoadingForm(true);
    Promise.allSettled([
      fetch(`${API_BASE}/providers/list`).then(r => r.json()),
      fetch(`${API_BASE}/plans/list`).then(r => r.json()),
      fetch(`${API_BASE}/members/next-id`).then(r => r.json()),
    ]).then(([provResult, plResult, nextIdResult]) => {
      if (provResult.status === 'fulfilled' && provResult.value.providers) {
        setProviders(provResult.value.providers);
      } else {
        setError('Could not load providers. Is the server running?');
      }
      if (plResult.status === 'fulfilled' && plResult.value.plans) {
        setPlans(plResult.value.plans);
      }
      if (nextIdResult.status === 'fulfilled' && nextIdResult.value.next_id) {
        setFormData(prev => ({ ...prev, member_id: nextIdResult.value.next_id }));
      }
    }).finally(() => setLoadingForm(false));
  };

  useEffect(() => { loadFormData(); }, []);

  const calculateAge = (dob) => {
    if (!dob) return '';
    const birth = new Date(dob);
    const today = new Date();
    let age = today.getFullYear() - birth.getFullYear();
    if (
      today.getMonth() < birth.getMonth() ||
      (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate())
    ) age--;
    return age.toString();
  };

  const fetchLocationByZip = async (zip, country) => {
    const countryCode = ZIP_COUNTRY_MAP[country];
    if (!countryCode || !zip) return;

    // Minimum ZIP length checks
    const minLen = countryCode === 'in' ? 6 : countryCode === 'ca' ? 6 : 4;
    if (zip.replace(/\s/g, '').length < minLen) return;

    setZipLoading(true);
    setZipStatus('');
    try {
      const res = await fetch(`https://api.zippopotam.us/${countryCode}/${zip.trim()}`);
      if (!res.ok) throw new Error('Not found');
      const data = await res.json();
      const place = data.places?.[0];
      if (place) {
        const fetchedCity  = place['place name'] || '';
        const fetchedState = place['state'] || '';
        setFormData(prev => ({
          ...prev,
          city: fetchedCity,
          state: fetchedState,
        }));
        setZipStatus('ok');
      }
    } catch {
      setZipStatus('error');
    } finally {
      setZipLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => {
      const updated = { ...prev, [name]: type === 'checkbox' ? checked : value };

      if (name === 'dob') {
        updated.age_str = calculateAge(value);
        if (!prev.enrollment_start) updated.enrollment_start = value;
      }

      // Reset state when country changes
      if (name === 'country') {
        updated.state    = '';
        updated.zip_code = '';
        setZipStatus('');
      }

      // Auto-fetch location on ZIP change
      if (name === 'zip_code') {
        const cleanZip = value.replace(/\s/g, '');
        const cc = ZIP_COUNTRY_MAP[prev.country];
        const triggerLen = cc === 'in' ? 6 : cc === 'ca' ? 6 : cc === 'us' ? 5 : 4;
        if (cleanZip.length === triggerLen) {
          fetchLocationByZip(value, prev.country);
        } else {
          setZipStatus('');
        }
      }

      return updated;
    });
  };

  const handleConditionToggle = (condition) => {
    setFormData(prev => {
      const exists = prev.chronic_conditions.includes(condition);
      return {
        ...prev,
        chronic_conditions: exists
          ? prev.chronic_conditions.filter(c => c !== condition)
          : [...prev.chronic_conditions, condition],
      };
    });
  };

  // ── Lifestyle handlers ──
  const handleLifestyleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => {
      const next = { ...prev, lifestyle: { ...prev.lifestyle, [name]: value } };
      // Auto-compute BMI when height & weight both provided
      const h = parseFloat(name === 'height_cm' ? value : next.lifestyle.height_cm);
      const w = parseFloat(name === 'weight_kg' ? value : next.lifestyle.weight_kg);
      if (h > 0 && w > 0) {
        const bmi = (w / ((h / 100) ** 2)).toFixed(1);
        next.lifestyle.bmi = bmi;
      }
      return next;
    });
  };

  // ── Family history handlers ──
  const addFamilyMember = () => {
    setFormData(prev => ({
      ...prev,
      family_history: [
        ...prev.family_history,
        { relation: '', name: '', alive: true, age_or_age_at_death: '',
          conditions: [], cause_of_death: '', notes: '' },
      ],
    }));
  };
  const removeFamilyMember = (idx) => {
    setFormData(prev => ({
      ...prev,
      family_history: prev.family_history.filter((_, i) => i !== idx),
    }));
  };
  const updateFamilyMember = (idx, field, value) => {
    setFormData(prev => ({
      ...prev,
      family_history: prev.family_history.map((fm, i) =>
        i === idx ? { ...fm, [field]: value } : fm
      ),
    }));
  };
  const toggleFamilyCondition = (idx, condition) => {
    setFormData(prev => ({
      ...prev,
      family_history: prev.family_history.map((fm, i) => {
        if (i !== idx) return fm;
        const has = (fm.conditions || []).includes(condition);
        return {
          ...fm,
          conditions: has
            ? fm.conditions.filter(c => c !== condition)
            : [...(fm.conditions || []), condition],
        };
      }),
    }));
  };

  // ── Medical history handlers (generic list add/remove/update) ──
  const addHistoryItem = (bucket, template) => {
    setFormData(prev => ({
      ...prev,
      medical_history: {
        ...prev.medical_history,
        [bucket]: [...(prev.medical_history[bucket] || []), template],
      },
    }));
  };
  const removeHistoryItem = (bucket, idx) => {
    setFormData(prev => ({
      ...prev,
      medical_history: {
        ...prev.medical_history,
        [bucket]: prev.medical_history[bucket].filter((_, i) => i !== idx),
      },
    }));
  };
  const updateHistoryItem = (bucket, idx, field, value) => {
    setFormData(prev => ({
      ...prev,
      medical_history: {
        ...prev.medical_history,
        [bucket]: prev.medical_history[bucket].map((it, i) =>
          i === idx ? { ...it, [field]: value } : it
        ),
      },
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/members/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      const data = await res.json();
      if (data.status === 'success') {
        onSuccess && onSuccess(data);
        onClose();
      } else {
        setError(data.error || 'Failed to add member');
      }
    } catch (err) {
      setError('Network error: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const currentStates = COUNTRY_STATES[formData.country] || [];

  return (
    <div className="add-member-modal">
      <div className="add-member-content">
        <div className="add-member-header">
          <div>
            <h2>Add New Member</h2>
            <p className="add-member-subtitle">Complete all sections for accurate care gap detection</p>
          </div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        {error && <div className="error-message">{error}</div>}

        <form onSubmit={handleSubmit}>

          {/* ── Section 1: Member Identity ─────────────────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">👤</span> Member Identity
            </div>
            <div className="form-grid form-grid-3">
              <div className="form-group">
                <label>Member ID <span className="section-note">Auto-assigned</span></label>
                <input type="text" name="member_id" value={formData.member_id}
                  onChange={handleChange} placeholder="Loading…" required
                  title="Auto-assigned — edit only if needed" />
              </div>
              <div className="form-group form-group-wide">
                <label>Full Name *</label>
                <input type="text" name="name" value={formData.name}
                  onChange={handleChange} placeholder="John Doe" required />
              </div>
              <div className="form-group">
                <label>Date of Birth *</label>
                <input type="date" name="dob" value={formData.dob}
                  onChange={handleChange} required />
              </div>
              <div className="form-group">
                <label>Age</label>
                <input type="text" name="age_str" value={formData.age_str}
                  readOnly placeholder="Auto-calculated" />
              </div>
              <div className="form-group">
                <label>Gender *</label>
                <select name="gender" value={formData.gender} onChange={handleChange} required>
                  <option value="Male">Male</option>
                  <option value="Female">Female</option>
                  <option value="Other">Other</option>
                </select>
              </div>
            </div>
          </div>

          {/* ── Section 2: Contact Information ────────────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">📬</span> Contact Information
              <span className="section-note">Email required for appointment notifications</span>
            </div>
            <div className="form-grid form-grid-2">
              <div className="form-group">
                <label>Email Address *</label>
                <input type="email" name="email" value={formData.email}
                  onChange={handleChange} placeholder="patient@email.com" required />
              </div>
              <div className="form-group">
                <label>Phone Number</label>
                <input type="tel" name="phone" value={formData.phone}
                  onChange={handleChange} placeholder="(555) 000-0000" />
              </div>
              <div className="form-group form-group-wide">
                <label>Street Address</label>
                <input type="text" name="street_address" value={formData.street_address}
                  onChange={handleChange} placeholder="123 Main Street" />
              </div>

              {/* Country */}
              <div className="form-group">
                <label>Country</label>
                <select name="country" value={formData.country} onChange={handleChange}>
                  {Object.keys(COUNTRY_STATES).map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              {/* ZIP / Postal Code with auto-fetch */}
              <div className="form-group">
                <label>
                  ZIP / Postal Code
                  {zipLoading && <span className="zip-fetching"> ↻ Fetching…</span>}
                  {zipStatus === 'ok'    && <span className="zip-ok"> ✓ Location found</span>}
                  {zipStatus === 'error' && <span className="zip-err"> ✗ Not found</span>}
                </label>
                <input
                  type="text"
                  name="zip_code"
                  value={formData.zip_code}
                  onChange={handleChange}
                  placeholder={formData.country === 'India' ? '400001' : formData.country === 'Canada' ? 'A1A 1A1' : '12345'}
                  maxLength="10"
                />
              </div>

              {/* City — auto-filled by ZIP fetch */}
              <div className="form-group">
                <label>City</label>
                <input type="text" name="city" value={formData.city}
                  onChange={handleChange} placeholder="Auto-filled or enter manually" />
              </div>

              {/* State — filtered by country */}
              <div className="form-group">
                <label>State / Province / Region</label>
                <select name="state" value={formData.state} onChange={handleChange}>
                  <option value="">Select</option>
                  {currentStates.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* ── Section 3: Demographics ───────────────────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">📊</span> Demographics
              <span className="section-note">Used for HEDIS measure stratification</span>
            </div>
            <div className="form-grid form-grid-3">
              <div className="form-group">
                <label>Race / Ethnicity</label>
                <select name="race" value={formData.race} onChange={handleChange}>
                  <option value="">Select</option>
                  <option value="White">White / Caucasian</option>
                  <option value="Black">Black / African American</option>
                  <option value="Hispanic">Hispanic / Latino</option>
                  <option value="Asian">Asian</option>
                  <option value="South Asian">South Asian (Indian / Pakistani / Bangladeshi)</option>
                  <option value="Pacific Islander">Native Hawaiian / Pacific Islander</option>
                  <option value="Native American">American Indian / Alaska Native</option>
                  <option value="Two or More">Two or More Races</option>
                  <option value="Other">Other</option>
                  <option value="Prefer not to say">Prefer not to say</option>
                </select>
              </div>
              <div className="form-group">
                <label>Preferred Language</label>
                <select name="language" value={formData.language} onChange={handleChange}>
                  {LANGUAGES.map(group => (
                    <optgroup key={group.group} label={group.group}>
                      {group.options.map(lang => (
                        <option key={lang} value={lang}>{lang}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div className="form-group form-group-checkbox">
                <label className="checkbox-label">
                  <input type="checkbox" name="tobacco_use"
                    checked={formData.tobacco_use} onChange={handleChange} />
                  <span>Current Tobacco User</span>
                </label>
                <p className="field-hint">Affects certain HEDIS counseling measures</p>
              </div>
            </div>
          </div>

          {/* ── Section 4: Clinical Background ───────────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">🩺</span> Clinical Background
              <span className="section-note">Select all active diagnoses — affects care gap exclusion criteria</span>
            </div>
            <div className="conditions-grid">
              {CHRONIC_OPTIONS.map(cond => (
                <label
                  key={cond}
                  className={`condition-chip ${formData.chronic_conditions.includes(cond) ? 'condition-chip--selected' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={formData.chronic_conditions.includes(cond)}
                    onChange={() => handleConditionToggle(cond)}
                    style={{ display: 'none' }}
                  />
                  {cond}
                </label>
              ))}
            </div>
            {formData.chronic_conditions.length > 0 && (
              <p className="conditions-summary">
                {formData.chronic_conditions.length} condition(s) selected — exclusion criteria will be evaluated automatically
              </p>
            )}
          </div>

          {/* ── Section 4B: Lifestyle ─────────────────────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">🏃</span> Lifestyle
              <span className="section-note">Optional — strengthens risk-adjusted gap recommendations</span>
            </div>
            <div className="form-grid form-grid-3">
              <div className="form-group">
                <label>Height (cm)</label>
                <input type="number" name="height_cm" min="50" max="260"
                  value={formData.lifestyle.height_cm}
                  onChange={handleLifestyleChange} placeholder="e.g. 170" />
              </div>
              <div className="form-group">
                <label>Weight (kg)</label>
                <input type="number" name="weight_kg" min="2" max="400"
                  value={formData.lifestyle.weight_kg}
                  onChange={handleLifestyleChange} placeholder="e.g. 72" />
              </div>
              <div className="form-group">
                <label>BMI <span className="section-note">Auto-calculated</span></label>
                <input type="text" name="bmi" value={formData.lifestyle.bmi}
                  onChange={handleLifestyleChange} placeholder="Auto" />
              </div>
              <div className="form-group">
                <label>Smoking Status</label>
                <select name="smoking_status" value={formData.lifestyle.smoking_status}
                  onChange={handleLifestyleChange}>
                  {SMOKING_OPTIONS.map(s => <option key={s} value={s}>{s || 'Select'}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Alcohol Use</label>
                <select name="alcohol_use" value={formData.lifestyle.alcohol_use}
                  onChange={handleLifestyleChange}>
                  {ALCOHOL_OPTIONS.map(s => <option key={s} value={s}>{s || 'Select'}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Exercise Frequency</label>
                <select name="exercise_frequency" value={formData.lifestyle.exercise_frequency}
                  onChange={handleLifestyleChange}>
                  {EXERCISE_OPTIONS.map(s => <option key={s} value={s}>{s || 'Select'}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Diet Type</label>
                <select name="diet_type" value={formData.lifestyle.diet_type}
                  onChange={handleLifestyleChange}>
                  {DIET_OPTIONS.map(s => <option key={s} value={s}>{s || 'Select'}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Average Sleep (hours/night)</label>
                <input type="number" name="sleep_hours_avg" min="0" max="24" step="0.5"
                  value={formData.lifestyle.sleep_hours_avg}
                  onChange={handleLifestyleChange} placeholder="e.g. 7" />
              </div>
              <div className="form-group">
                <label>Stress Level</label>
                <select name="stress_level" value={formData.lifestyle.stress_level}
                  onChange={handleLifestyleChange}>
                  {STRESS_OPTIONS.map(s => <option key={s} value={s}>{s || 'Select'}</option>)}
                </select>
              </div>
              <div className="form-group form-group-wide" style={{ gridColumn: '1 / -1' }}>
                <label>Lifestyle Notes</label>
                <textarea name="notes" value={formData.lifestyle.notes}
                  onChange={handleLifestyleChange} rows="2"
                  placeholder="Additional context (optional)" />
              </div>
            </div>
          </div>

          {/* ── Section 4C: Family / Ancestral History ──────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">🧬</span> Family / Ancestral History
              <span className="section-note">
                First-degree relatives' conditions elevate hereditary risk and re-prioritize screenings
              </span>
            </div>
            {formData.family_history.length === 0 && (
              <p className="empty-hint">No relatives added yet. Click below to add the member's parents, siblings, or grandparents.</p>
            )}
            {formData.family_history.map((fm, idx) => (
              <div key={idx} className="family-member-card">
                <div className="family-member-header">
                  <strong>Relative #{idx + 1}</strong>
                  <button type="button" className="btn-remove" onClick={() => removeFamilyMember(idx)}>
                    Remove
                  </button>
                </div>
                <div className="form-grid form-grid-3">
                  <div className="form-group">
                    <label>Relation *</label>
                    <select value={fm.relation}
                      onChange={(e) => updateFamilyMember(idx, 'relation', e.target.value)}>
                      <option value="">Select</option>
                      {FAMILY_RELATIONS.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Name (optional)</label>
                    <input type="text" value={fm.name}
                      onChange={(e) => updateFamilyMember(idx, 'name', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label>Age / Age at Death</label>
                    <input type="text" value={fm.age_or_age_at_death}
                      onChange={(e) => updateFamilyMember(idx, 'age_or_age_at_death', e.target.value)} />
                  </div>
                  <div className="form-group form-group-checkbox">
                    <label className="checkbox-label">
                      <input type="checkbox" checked={fm.alive}
                        onChange={(e) => updateFamilyMember(idx, 'alive', e.target.checked)} />
                      <span>Alive</span>
                    </label>
                  </div>
                  {!fm.alive && (
                    <div className="form-group form-group-wide">
                      <label>Cause of Death</label>
                      <input type="text" value={fm.cause_of_death}
                        onChange={(e) => updateFamilyMember(idx, 'cause_of_death', e.target.value)} />
                    </div>
                  )}
                </div>
                <div className="form-group form-group-wide" style={{ marginTop: 8 }}>
                  <label>Known Conditions</label>
                  <div className="conditions-grid">
                    {HEREDITARY_CONDITIONS.map(cond => (
                      <label key={cond}
                        className={`condition-chip ${(fm.conditions || []).includes(cond) ? 'condition-chip--selected' : ''}`}>
                        <input type="checkbox"
                          checked={(fm.conditions || []).includes(cond)}
                          onChange={() => toggleFamilyCondition(idx, cond)}
                          style={{ display: 'none' }} />
                        {cond}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="form-group form-group-wide" style={{ marginTop: 8 }}>
                  <label>Notes</label>
                  <textarea value={fm.notes} rows="2"
                    onChange={(e) => updateFamilyMember(idx, 'notes', e.target.value)} />
                </div>
              </div>
            ))}
            <button type="button" className="btn-add-row" onClick={addFamilyMember}>
              + Add Relative
            </button>
          </div>

          {/* ── Section 4D: Medical History ─────────────────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">📋</span> Medical History
              <span className="section-note">Past/current conditions, surgeries, allergies, medications</span>
            </div>

            {/* Current Conditions */}
            <HistoryBucket
              title="Current Conditions"
              items={formData.medical_history.current_conditions}
              fields={[
                { name: 'name', label: 'Condition', type: 'text', placeholder: 'e.g. Hypertension' },
                { name: 'onset_year', label: 'Onset Year', type: 'text', placeholder: 'YYYY', width: 'sm' },
                { name: 'notes', label: 'Notes', type: 'text', placeholder: '' },
              ]}
              onAdd={() => addHistoryItem('current_conditions', { name: '', onset_year: '', notes: '' })}
              onRemove={(i) => removeHistoryItem('current_conditions', i)}
              onUpdate={(i, f, v) => updateHistoryItem('current_conditions', i, f, v)}
            />

            {/* Past Conditions */}
            <HistoryBucket
              title="Past Conditions (Resolved)"
              items={formData.medical_history.past_conditions}
              fields={[
                { name: 'name', label: 'Condition', type: 'text', placeholder: 'e.g. Pneumonia' },
                { name: 'onset_year', label: 'Year', type: 'text', placeholder: 'YYYY', width: 'sm' },
                { name: 'notes', label: 'Notes', type: 'text' },
              ]}
              onAdd={() => addHistoryItem('past_conditions', { name: '', onset_year: '', notes: '' })}
              onRemove={(i) => removeHistoryItem('past_conditions', i)}
              onUpdate={(i, f, v) => updateHistoryItem('past_conditions', i, f, v)}
            />

            {/* Surgeries */}
            <HistoryBucket
              title="Surgeries"
              items={formData.medical_history.surgeries}
              fields={[
                { name: 'name', label: 'Procedure', type: 'text', placeholder: 'e.g. Appendectomy' },
                { name: 'year', label: 'Year', type: 'text', placeholder: 'YYYY', width: 'sm' },
                { name: 'notes', label: 'Notes', type: 'text' },
              ]}
              onAdd={() => addHistoryItem('surgeries', { name: '', year: '', notes: '' })}
              onRemove={(i) => removeHistoryItem('surgeries', i)}
              onUpdate={(i, f, v) => updateHistoryItem('surgeries', i, f, v)}
            />

            {/* Allergies */}
            <HistoryBucket
              title="Allergies"
              items={formData.medical_history.allergies}
              fields={[
                { name: 'substance', label: 'Substance', type: 'text', placeholder: 'e.g. Penicillin' },
                { name: 'severity', label: 'Severity', type: 'select', options: ['', 'Mild', 'Moderate', 'Severe', 'Anaphylaxis'], width: 'sm' },
                { name: 'reaction', label: 'Reaction', type: 'text', placeholder: 'e.g. Rash' },
              ]}
              onAdd={() => addHistoryItem('allergies', { substance: '', severity: '', reaction: '' })}
              onRemove={(i) => removeHistoryItem('allergies', i)}
              onUpdate={(i, f, v) => updateHistoryItem('allergies', i, f, v)}
            />

            {/* Medications */}
            <HistoryBucket
              title="Current Medications"
              items={formData.medical_history.medications}
              fields={[
                { name: 'name', label: 'Medication', type: 'text', placeholder: 'e.g. Metformin' },
                { name: 'dose', label: 'Dose', type: 'text', placeholder: 'e.g. 500mg BID', width: 'sm' },
                { name: 'purpose', label: 'Purpose', type: 'text', placeholder: 'e.g. Diabetes' },
              ]}
              onAdd={() => addHistoryItem('medications', { name: '', dose: '', purpose: '' })}
              onRemove={(i) => removeHistoryItem('medications', i)}
              onUpdate={(i, f, v) => updateHistoryItem('medications', i, f, v)}
            />

            {/* Immunizations */}
            <HistoryBucket
              title="Immunizations"
              items={formData.medical_history.immunizations}
              fields={[
                { name: 'name', label: 'Vaccine', type: 'text', placeholder: 'e.g. Influenza' },
                { name: 'year', label: 'Year', type: 'text', placeholder: 'YYYY', width: 'sm' },
              ]}
              onAdd={() => addHistoryItem('immunizations', { name: '', year: '' })}
              onRemove={(i) => removeHistoryItem('immunizations', i)}
              onUpdate={(i, f, v) => updateHistoryItem('immunizations', i, f, v)}
            />
          </div>

          {/* ── Section 5: Insurance & Enrollment ────────────────── */}
          <div className="form-section">
            <div className="form-section-title">
              <span className="section-icon">💳</span> Insurance &amp; Enrollment
            </div>
            <div className="form-grid form-grid-2">
              <div className="form-group">
                <label>Insurance Type *</label>
                <select name="insurance_type" value={formData.insurance_type} onChange={handleChange} required>
                  <option value="Commercial">Commercial</option>
                  <option value="Medicare">Medicare</option>
                  <option value="Medicaid">Medicaid</option>
                  <option value="Dual Eligible">Dual Eligible (Medicare + Medicaid)</option>
                  <option value="Self-Pay">Self-Pay</option>
                </select>
              </div>
              <div className="form-group">
                <label>Benefit Plan *</label>
                <select name="plan_id" value={formData.plan_id} onChange={handleChange} required>
                  <option value="">Select Plan</option>
                  {plans.map(p => (
                    <option key={p.plan_id} value={p.plan_id}>
                      {p.plan_id} — Copay: ${p.copay}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Primary Care Provider *</label>
                {loadingForm ? (
                  <select disabled><option>Loading providers…</option></select>
                ) : providers.length === 0 ? (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <select name="pcp_id" disabled style={{ flex: 1 }}>
                      <option>No providers found</option>
                    </select>
                    <button type="button" onClick={loadFormData}
                      style={{ padding: '6px 12px', fontSize: '0.8rem', cursor: 'pointer',
                               background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 6 }}>
                      Retry
                    </button>
                  </div>
                ) : (
                  <select name="pcp_id" value={formData.pcp_id} onChange={handleChange} required>
                    <option value="">Select Provider</option>
                    {providers.map(p => (
                      <option key={p.provider_id} value={p.provider_id}>
                        {p.name} — {p.specialty}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="form-group">
                <label>Enrollment Start</label>
                <input type="date" name="enrollment_start" value={formData.enrollment_start}
                  onChange={handleChange} />
              </div>
              <div className="form-group">
                <label>Enrollment End</label>
                <input type="date" name="enrollment_end" value={formData.enrollment_end}
                  onChange={handleChange} />
              </div>
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="btn-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-submit" disabled={loading}>
              {loading ? 'Adding Member…' : 'Add Member to Graph'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Reusable sub-component for each medical-history bucket
function HistoryBucket({ title, items, fields, onAdd, onRemove, onUpdate }) {
  return (
    <div className="history-bucket">
      <div className="history-bucket-title">{title}</div>
      {items.length === 0 && (
        <p className="empty-hint empty-hint-sm">No entries. Click "+ Add" to create one.</p>
      )}
      {items.map((item, idx) => (
        <div key={idx} className="history-row">
          {fields.map(f => (
            <div key={f.name} className={`form-group history-field history-field-${f.width || 'md'}`}>
              <label>{f.label}</label>
              {f.type === 'select' ? (
                <select value={item[f.name] || ''}
                  onChange={(e) => onUpdate(idx, f.name, e.target.value)}>
                  {(f.options || []).map(opt => (
                    <option key={opt} value={opt}>{opt || 'Select'}</option>
                  ))}
                </select>
              ) : (
                <input type={f.type || 'text'} value={item[f.name] || ''}
                  placeholder={f.placeholder || ''}
                  onChange={(e) => onUpdate(idx, f.name, e.target.value)} />
              )}
            </div>
          ))}
          <button type="button" className="btn-remove btn-remove-sm"
            onClick={() => onRemove(idx)} title="Remove row">×</button>
        </div>
      ))}
      <button type="button" className="btn-add-row" onClick={onAdd}>+ Add</button>
    </div>
  );
}

export default AddMember;
