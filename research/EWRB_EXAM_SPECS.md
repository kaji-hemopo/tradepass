# EWRB Electrician Exams — Research Spec

**Sourced**: EWRB.govt.nz, Aspeq, E-tec, TradeLab, Stuvia/Gaviki exam dumps  
**Date**: 2026-04-10  
**Status**: COMPLETE

---

## Overview

The **Electrical Workers Registration Board (EWRB)** governs electrician registration in New Zealand. Two written exams are mandatory for registration:

| Exam | Purpose | Prerequisite |
|------|---------|--------------|
| **Electricians Theory** | Tests electrical theory knowledge | None (but 8,000 hrs practical + TLC required for full registration) |
| **Electricians Regulations** | Tests application of Electricity Act, Regulations, AS/NZS 3000 | Usually taken after or alongside Theory |

Exams are **multiple-choice**, administered by **Aspeq Limited** online at Aspeq facilities. Fee: **$149.50 + GST** per exam. Re-sits available almost immediately; after 3 attempts within 3 months, Board mandates a 3-month wait.

---

## Electricians Theory Exam

### Format
- **Questions**: ~50 multiple choice
- **Time Limit**: 2 hours (120 minutes)
- **Pass Mark**: ~70–75% (approx 35–38 correct answers)
- **Administered by**: Aspeq (online at their facilities)

### Syllabus Topics (E-tec course structure)

| Topic | Weight | Notes |
|-------|--------|-------|
| **Supply Systems** | High | 3-phase, distribution, earthing arrangements (TT, TN, IT) |
| **Protection** | High | Overcurrent, earth fault, RCDs, discrimination |
| **Safety** | High | Safe working practices, PPE, testing safety |
| **Motors & Motor Starters** | Medium | DOL, star-delta, soft starters, overloads |
| **Switchboards** | Medium | Distribution boards, circuit arrangements |
| **Transformers** | Medium | Isolation, step-up/step-down, connections |
| **Lighting** | Medium | Luminaires, design, LED, emergency lighting |
| **Testing** | High | Insulation resistance, earth loop impedance, polarity, RCD testing |
| **Semi-conductors** | Low | Basic diode, transistor circuits (lightweight) |
| **Cables** | High | Current-carrying capacity, cable selection, volt drop |

### Key Formulas Required
- Voltage Drop: `V = I × R` or `V = k × I × L` (k factor from AS/NZS 3000 Tables)
- Power: `P = V × I × √3 × cosφ` (3-phase)
- Ohm's Law: `V = I × R`
- Cable sizing via AS/NZS 3008 tables
- Fault loop impedance calculations

---

## Electricians Regulations Exam

### Format
- **Questions**: ~50 multiple choice
- **Time Limit**: 2 hours (120 minutes)  
- **Pass Mark**: ~70–75%
- **Administered by**: Aspeq (same as Theory)

### Syllabus Topics

| Topic | Weight | Notes |
|-------|--------|-------|
| **Electricity Act 1992** | Medium | Core obligations, licensing, Board jurisdiction |
| **Electrical (Safety) Regulations** | High | Consumer installations, defined work, inspection/test requirements |
| **AS/NZS 3000 (Wiring Rules)** | **VERY HIGH** | The single most failsafe topic — application to installation design |
| **Maximum Demand** | High | Calculation methods, diversity factors |
| **Voltage Drop** | **VERY HIGH** | AS/NZS 3000 compliance, 5% max for lighting, 7% overall |
| **Fault Loop Impedance** | High | Zs verification, prospective fault current |
| **Testing & Verification** | High | Procedures, documentation, test instrument requirements |
| **Injury Notification** | Medium | Notifiable work, Board notification obligations |

### AS/NZS 3000 Key Requirements (High Failure Areas)

**Voltage Drop (Clause 3.6)**
- Maximum voltage drop from point of supply to furthest outlet:
  - **Lighting**: 5% of nominal voltage (11.5V on 230V)
  - **Other loads**: 7% of nominal voltage (16.1V on 230V)
- Conductors must be sized to comply, not just for current capacity

**Earth Fault Loop Impedance (Clause 5)**
- All circuits must have earth fault loop impedance low enough to ensure rapid operation of protective devices
- `Zs = Ze + Zt` (external + circuit loop)
- Tables specify maximum loop impedance per circuit type/protective device

**Circuit Design (AS/NZS 3008)**
- Cable selection based on current-carrying capacity and voltage drop
- Installation method, ambient temperature, grouping factors
- Diversity factors for final circuits

---

## High-Failure Topics (Confirmed from Exam Prep Providers)

| Rank | Topic | Why It Fails People |
|------|-------|---------------------|
| **1** | **Voltage Drop Calculations** | Candidates memorize formulas but can't apply AS/NZS 3000 Tables correctly; k-factor usage confused |
| **2** | **AS/NZS 3000 Application** | Too many clauses; candidates don't read the standard enough |
| **3** | **Fault Loop Impedance** | Confused with voltage drop; Zs vs Ze vs Zt not understood |
| **4** | **Insulation Resistance Testing** | Test voltage values, minimum values (1MΩ), applied to correct circuits |
| **5** | **Protection & Discrimination** | Selectivity between OCPDs and RCDs; coordination |
| **6** | **Maximum Demand** | Diversity factors misapplied; load assessment wrong |

---

## Exam Question Style (from Stuvia/Gaviki dumps)

Sample question styles:

**Q: Insulation resistance**
> "What is the minimum value of the permitted test result for the insulation resistance test of a three-phase, 400V, mains cable?"
> Answer: **1MΩ**

**Q: Testing documentation**
> "When carrying out testing on a low voltage electrical installation, which document details the tests and checks required to be carried out?"
> Answer: **AS/NZS 3000**

**Q: Voltage drop**
> "What is the maximum permitted voltage drop for a lighting circuit in a 230V installation?"
> Answer: **11.5V (5% of 230V)**

**Q: Circuit breaker coordination**
> "Which device provides protection against both overcurrent and earth fault?"
> Answer: **RCBO (Residual Current Breaker with Overload)**

---

## References & Study Materials

| Resource | URL | Purpose |
|----------|-----|---------|
| EWRB Official | ewrb.govt.nz | Exam booking, regulations prescription |
| Aspeq (exam agent) | aspeq.com | Exam booking |
| E-tec | etec.ac.nz | Theory course provider |
| TradeLab | courses.tradelab.co | Exam refresher (paid course) |
| Stuvia (exam dumps) | stuvia.com | 2025/2026 actual exam Q&A |
| AS/NZS 3000 | Standards NZ | Wiring Rules (mandatory reference) |
| AS/NZS 3008 | Standards NZ | Cable selection tables |

---

## TradePass MVP Targets

For the TradePass spaced-repetition engine MVP, seed questions should prioritize:

1. **Voltage Drop** (20% of question bank) — most failed topic
2. **AS/NZS 3000 Application** (20%) — most broad topic  
3. **Fault Loop Impedance** (15%)
4. **Insulation Resistance** (10%)
5. **Protection & Discrimination** (10%)
6. **Maximum Demand** (10%)
7. **Other Theory Topics** (15%)

Question format: **Single best answer multiple choice** (4 options, 1 correct).  
Difficulty: **Exam-level** (not textbook-level — real questions are specific and tricky).

---

*Research complete. TASK 1 DONE.*
