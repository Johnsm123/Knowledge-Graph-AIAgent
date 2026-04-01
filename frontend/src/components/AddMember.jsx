import { useState, useEffect } from 'react';
import './AddMember.css';

function AddMember({ onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    member_id: '',
    name: '',
    dob: '',
    gender: 'Male',
    pcp_id: '',
    plan_id: '',
    zip_code: '',
    enrollment_start: '',
    enrollment_end: '2025-12-31',
    age_str: ''
  });

  const [providers, setProviders] = useState([]);
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchProviders();
    fetchPlans();
  }, []);

  const fetchProviders = async () => {
    try {
      const response = await fetch('http://localhost:5001/api/v1/providers/list');
      const data = await response.json();
      setProviders(data.providers || []);
    } catch (err) {
      console.error('Failed to fetch providers:', err);
    }
  };

  const fetchPlans = async () => {
    try {
      const response = await fetch('http://localhost:5001/api/v1/plans/list');
      const data = await response.json();
      setPlans(data.plans || []);
    } catch (err) {
      console.error('Failed to fetch plans:', err);
    }
  };

  const calculateAge = (dob) => {
    if (!dob) return '';
    const birthDate = new Date(dob);
    const today = new Date();
    let age = today.getFullYear() - birthDate.getFullYear();
    const monthDiff = today.getMonth() - birthDate.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }
    return age.toString();
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => {
      const updated = { ...prev, [name]: value };
      
      // Auto-calculate age when DOB changes
      if (name === 'dob') {
        updated.age_str = calculateAge(value);
        updated.enrollment_start = value; // Default enrollment start to DOB
      }
      
      return updated;
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const response = await fetch('http://localhost:5001/api/v1/members/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      const data = await response.json();

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

  return (
    <div className="add-member-modal">
      <div className="add-member-content">
        <div className="add-member-header">
          <h2>Add New Member</h2>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        {error && <div className="error-message">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <div className="form-group">
              <label>Member ID *</label>
              <input
                type="text"
                name="member_id"
                value={formData.member_id}
                onChange={handleChange}
                placeholder="M0031"
                required
              />
            </div>

            <div className="form-group">
              <label>Full Name *</label>
              <input
                type="text"
                name="name"
                value={formData.name}
                onChange={handleChange}
                placeholder="John Doe"
                required
              />
            </div>

            <div className="form-group">
              <label>Date of Birth *</label>
              <input
                type="date"
                name="dob"
                value={formData.dob}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-group">
              <label>Age</label>
              <input
                type="text"
                name="age_str"
                value={formData.age_str}
                readOnly
                placeholder="Auto-calculated"
              />
            </div>

            <div className="form-group">
              <label>Gender *</label>
              <select
                name="gender"
                value={formData.gender}
                onChange={handleChange}
                required
              >
                <option value="Male">Male</option>
                <option value="Female">Female</option>
              </select>
            </div>

            <div className="form-group">
              <label>ZIP Code</label>
              <input
                type="text"
                name="zip_code"
                value={formData.zip_code}
                onChange={handleChange}
                placeholder="12345"
                maxLength="5"
              />
            </div>

            <div className="form-group">
              <label>Primary Care Provider *</label>
              <select
                name="pcp_id"
                value={formData.pcp_id}
                onChange={handleChange}
                required
              >
                <option value="">Select Provider</option>
                {providers.map(p => (
                  <option key={p.provider_id} value={p.provider_id}>
                    {p.name} - {p.specialty}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Benefit Plan *</label>
              <select
                name="plan_id"
                value={formData.plan_id}
                onChange={handleChange}
                required
              >
                <option value="">Select Plan</option>
                {plans.map(p => (
                  <option key={p.plan_id} value={p.plan_id}>
                    {p.plan_id} (Copay: ${p.copay})
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Enrollment Start</label>
              <input
                type="date"
                name="enrollment_start"
                value={formData.enrollment_start}
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label>Enrollment End</label>
              <input
                type="date"
                name="enrollment_end"
                value={formData.enrollment_end}
                onChange={handleChange}
              />
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="btn-cancel" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-submit" disabled={loading}>
              {loading ? 'Adding...' : 'Add Member'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default AddMember;
