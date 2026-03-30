# Installation & Deployment Checklist

## ✅ Pre-Installation Checklist

- [ ] Python 3.8+ installed and verified

  ```bash
  python --version
  ```

- [ ] pip package manager working

  ```bash
  pip --version
  ```

- [ ] Neo4j Aura account created
  - [ ] Free tier instance created
  - [ ] Connection URI copied
  - [ ] Username and password noted
  - [ ] Instance is running

- [ ] OpenAI account created
  - [ ] API key generated
  - [ ] Account has credits
  - [ ] API is enabled

- [ ] Git installed (optional but recommended)
  ```bash
  git --version
  ```

---

## 📥 Installation Steps

### Step 1: Project Setup

- [ ] Project directory created or cloned
- [ ] Navigated to project root
  ```bash
  cd knowledge-graph-AIAgents
  ```

### Step 2: Virtual Environment

- [ ] Virtual environment created
  ```bash
  python -m venv venv
  ```
- [ ] Virtual environment activated
  - [ ] **Windows**: `venv\Scripts\activate`
  - [ ] **Mac/Linux**: `source venv/bin/activate`

### Step 3: Dependencies

- [ ] Requirements file reviewed
  ```bash
  cat requirements.txt
  ```
- [ ] Dependencies installed
  ```bash
  pip install -r requirements.txt
  ```
- [ ] Installation verified
  ```bash
  pip list
  ```

### Step 4: Environment Configuration

- [ ] `.env` file created from template
  ```bash
  cp .env.example .env
  ```
- [ ] `.env` file edited with credentials
  - [ ] NEO4J_URI set correctly
  - [ ] NEO4J_USERNAME set
  - [ ] NEO4J_PASSWORD set securely
  - [ ] OPENAI_API_KEY set
  - [ ] OPENAI_MODEL set (gpt-4 or gpt-3.5-turbo)

- [ ] `OAI_CONFIG_LIST` file created/updated
  ```json
  [
    {
      "model": "gpt-4",
      "api_key": "sk-...",
      "api_type": "openai",
      "api_base": "https://api.openai.com/v1"
    }
  ]
  ```

### Step 5: Database Initialization

- [ ] Neo4j connection tested manually

  ```python
  from src.neo4j_connection import get_knowledge_graph
  kg = get_knowledge_graph()
  kg.verify_connection()
  ```

- [ ] Knowledge graph initialized

  ```bash
  python -m src.init_knowledge_graph
  ```

- [ ] Database contents verified
  - [ ] Conditions created
  - [ ] Symptoms created
  - [ ] Medications created
  - [ ] Relationships created

### Step 6: Application Testing

- [ ] Application runs (interactive mode)

  ```bash
  python -m src.main
  ```

- [ ] API starts successfully

  ```bash
  python -m src.api
  ```

- [ ] Health endpoint responds
  ```bash
  curl http://localhost:5000/api/v1/health
  ```

---

## 🧪 Post-Installation Testing

### Unit Tests

- [ ] Test suite runs without errors
  ```bash
  pytest tests/ -v
  ```

### API Tests

- [ ] Create patient endpoint

  ```bash
  curl -X POST http://localhost:5000/api/v1/patients \
    -H "Content-Type: application/json" \
    -d '{"patient_id":"TEST001","name":"Test Patient","age":50,"gender":"M"}'
  ```

- [ ] Get summary endpoint

  ```bash
  curl http://localhost:5000/api/v1/patients/TEST001/summary
  ```

- [ ] Add condition endpoint
  ```bash
  curl -X POST http://localhost:5000/api/v1/patients/TEST001/conditions \
    -H "Content-Type: application/json" \
    -d '{"condition_id":"COND001","diagnosed_date":"2023-01-01","status":"active"}'
  ```

### Analysis Tests

- [ ] Analysis endpoint works

  ```bash
  curl -X POST http://localhost:5000/api/v1/patients/TEST001/analysis
  ```

- [ ] Predictions work
  ```bash
  curl -X POST http://localhost:5000/api/v1/patients/TEST001/predict-outcomes \
    -H "Content-Type: application/json" \
    -d '{"timeframe_months":12}'
  ```

---

## 🚀 Production Deployment Checklist

### Pre-Deployment

- [ ] Code review completed
- [ ] All tests passing
- [ ] Security audit performed
- [ ] Performance benchmarks established
- [ ] Documentation updated

### Infrastructure

- [ ] Production Neo4j instance provisioned
  - [ ] Proper backup configured
  - [ ] Size: 10GB+ recommended
  - [ ] Encryption enabled
  - [ ] Access controls configured

- [ ] Production OpenAI account setup
  - [ ] Billing method configured
  - [ ] Rate limits reviewed
  - [ ] Usage monitoring enabled

- [ ] Server/Cloud infrastructure ready
  - [ ] Docker image built and tested
  - [ ] Kubernetes manifests prepared
  - [ ] Load balancer configured
  - [ ] SSL/TLS certificates ready

### Application Configuration

- [ ] Production `.env` created securely
  - [ ] Secrets manager integration
  - [ ] No hardcoded credentials
  - [ ] Environment-specific settings

- [ ] Logging configured
  - [ ] Central logging enabled
  - [ ] Log rotation configured
  - [ ] Monitoring alerts set

- [ ] Monitoring & Alerts
  - [ ] Health checks configured
  - [ ] Error tracking enabled (e.g., Sentry)
  - [ ] Performance monitoring enabled
  - [ ] Database monitoring enabled

### Security Hardening

- [ ] Authentication implemented
  - [ ] JWT tokens configured
  - [ ] Token refresh logic
  - [ ] Secure storage of secrets

- [ ] Authorization configured
  - [ ] RBAC implemented
  - [ ] API rate limiting enabled
  - [ ] CORS properly configured

- [ ] Data protection
  - [ ] Encryption at rest enabled
  - [ ] Encryption in transit enabled
  - [ ] Data retention policies configured
  - [ ] HIPAA compliance verified

### Deployment

- [ ] Deployment script created
- [ ] Database migrations applied
- [ ] Initial data loaded
- [ ] Smoke tests passed
  - [ ] API endpoints respond
  - [ ] Database connectivity works
  - [ ] LLM integration works

### Post-Deployment

- [ ] Application running in production
- [ ] Health checks passing
- [ ] Logs being collected
- [ ] Monitoring alerts active
- [ ] User documentation available
- [ ] Support processes established

---

## 📊 Performance Benchmarks

After deployment, verify:

- [ ] API response time < 10s (summaries)
- [ ] Analysis time: 1-3 minutes
- [ ] Database query time < 100ms (p95)
- [ ] API availability > 99.9%
- [ ] Error rate < 0.1%

---

## 🔄 Regular Maintenance

### Daily

- [ ] Check error logs
- [ ] Monitor API usage
- [ ] Verify backups completed

### Weekly

- [ ] Review performance metrics
- [ ] Check Neo4j database health
- [ ] Update dependencies (if needed)

### Monthly

- [ ] Security patches applied
- [ ] Database optimization
- [ ] Cost analysis
- [ ] Backup restoration test

### Quarterly

- [ ] Security audit
- [ ] Performance review
- [ ] Capacity planning
- [ ] Disaster recovery test

---

## 📋 Troubleshooting Checklist

### Connection Issues

- [ ] Neo4j instance running?
- [ ] URI format correct (neo4j+s://)?
- [ ] Firewall allows port 7687?
- [ ] Credentials correct?
- [ ] Network connectivity working?

### API Issues

- [ ] Python virtual environment activated?
- [ ] All dependencies installed?
- [ ] Port 5000 available?
- [ ] Environment variables loaded?
- [ ] OpenAI API key valid?

### Performance Issues

- [ ] Database has proper indexes?
- [ ] Queries optimized?
- [ ] Connection pooling configured?
- [ ] Sufficient resources allocated?
- [ ] Network latency acceptable?

### Data Issues

- [ ] Patient data complete?
- [ ] Relationships properly created?
- [ ] No duplicate records?
- [ ] Data validates correctly?

---

## 📝 Documentation Checklist

- [ ] README.md - Complete and accurate
- [ ] GETTING_STARTED.md - Clear and tested
- [ ] API_REFERENCE.md - All endpoints documented
- [ ] ADVANCED_USAGE.md - Advanced features covered
- [ ] PROJECT_SUMMARY.md - Architecture clear
- [ ] QUICK_REFERENCE.md - Quick commands listed
- [ ] Inline code comments - Clear and helpful
- [ ] Error messages - Helpful and actionable

---

## ✨ Quality Assurance

- [ ] Code style checker passed

  ```bash
  flake8 src/
  ```

- [ ] Code quality analysis

  ```bash
  pylint src/
  ```

- [ ] Type checking (if using)

  ```bash
  mypy src/
  ```

- [ ] Documentation quality
  - [ ] No broken links
  - [ ] Examples run successfully
  - [ ] API docs accurate

---

## 🎯 Sign-Off

- [ ] Development team sign-off
- [ ] QA team sign-off
- [ ] Security team sign-off
- [ ] Operations team sign-off
- [ ] Business team approval

**Deployment Date**: ******\_\_\_******
**Deployed By**: ******\_\_\_******
**Version**: 1.0.0

---

## 📞 Support Contact

**Primary Contact**: ******\_\_\_******
**Secondary Contact**: ******\_\_\_******
**On-Call Number**: ******\_\_\_******
**Support Email**: ******\_\_\_******

---

**Last Updated: March 2026**
