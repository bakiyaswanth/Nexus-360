-- =====================================================================
-- ACTION360 :: 03 Demo personas (hand-crafted, synthetic)
-- Six customers designed to produce visibly different next-best-actions.
--   C10238  Premier, 3 products, repeated unresolved complaints, competitor mention, rate reset in 21 days
--           -> SERVICE RECOVERY first (retention offer is secondary, not a blind discount)
--   C10417  Job loss, 2 missed EMIs  -> PAYMENT-PLAN discussion (retention discount NOT eligible)
--   C10555  Promotion, rising card spend, perfect payments -> PRODUCT UPGRADE (premium card)
--   C10789  Newborn, individual health only, no life cover -> COVERAGE REVIEW (family floater)
--   C10901  Stable, low risk -> RULES ONLY, no LLM call, monitor
--   C11024  Motor renewal in 28 days + delayed claim -> CLAIM FOLLOW-UP; loyalty discount NOT eligible
-- =====================================================================
USE WAREHOUSE ACTION360_WH;
USE SCHEMA ACTION360_DB.CORE;

DELETE FROM CALL_TRANSCRIPT WHERE CUSTOMER_ID IN ('C10238','C10417','C10555','C10789','C10901','C11024');
DELETE FROM FACT_INTERACTION WHERE CUSTOMER_ID IN ('C10238','C10417','C10555','C10789','C10901','C11024');
DELETE FROM FACT_CLAIM_OR_LOAN_EVENT WHERE CUSTOMER_ID IN ('C10238','C10417','C10555','C10789','C10901','C11024');

UPDATE DIM_CUSTOMER SET FULL_NAME = CASE CUSTOMER_ID
  WHEN 'C10238' THEN 'Arjun Mehta' WHEN 'C10417' THEN 'Rohan Das' WHEN 'C10555' THEN 'Kavya Iyer'
  WHEN 'C10789' THEN 'Karthik Nair' WHEN 'C10901' THEN 'Lakshmi Rao' WHEN 'C11024' THEN 'Priya Kulkarni' END,
  CITY = CASE CUSTOMER_ID WHEN 'C10238' THEN 'Bengaluru' WHEN 'C10417' THEN 'Hyderabad' WHEN 'C10555' THEN 'Chennai'
  WHEN 'C10789' THEN 'Kochi' WHEN 'C10901' THEN 'Pune' ELSE 'Mumbai' END,
  STATE = CASE CUSTOMER_ID WHEN 'C10238' THEN 'Karnataka' WHEN 'C10417' THEN 'Telangana' WHEN 'C10555' THEN 'Tamil Nadu'
  WHEN 'C10789' THEN 'Kerala' WHEN 'C10901' THEN 'Maharashtra' ELSE 'Maharashtra' END,
  PREFERRED_CHANNEL = CASE CUSTOMER_ID WHEN 'C10238' THEN 'CALL' WHEN 'C10417' THEN 'WHATSAPP' WHEN 'C10555' THEN 'APP'
  WHEN 'C10789' THEN 'CALL' WHEN 'C10901' THEN 'EMAIL' ELSE 'EMAIL' END,
  MONTHLY_INCOME = CASE CUSTOMER_ID WHEN 'C10238' THEN 420000 WHEN 'C10417' THEN 62000 WHEN 'C10555' THEN 210000
  WHEN 'C10789' THEN 140000 WHEN 'C10901' THEN 55000 ELSE 160000 END
WHERE CUSTOMER_ID IN ('C10238','C10417','C10555','C10789','C10901','C11024');

-- Make the premier relationship clearly high-value
UPDATE FACT_ACCOUNT SET PRINCIPAL_OR_SUM_ASSURED = 14500000, OUTSTANDING_BALANCE = 11200000, INTEREST_RATE = 9.15, MONTHLY_INSTALMENT = 128000
 WHERE ACCOUNT_ID = 'AC10238-1';

INSERT INTO FACT_INTERACTION (INTERACTION_ID, CUSTOMER_ID, INDUSTRY_TYPE, INTERACTION_TS, CHANNEL, TOPIC, IS_COMPLAINT, RESOLUTION_STATUS, RULE_SENTIMENT, NOTE, HAS_TRANSCRIPT, TEMPLATE_ID)
VALUES
-- C10238 Arjun Mehta
('IC10238-1','C10238','LENDING','2026-08-04 11:20:00','APP','Statement request',FALSE,'RESOLVED',0.2,'Downloaded home loan interest certificate.',FALSE,'PERSONA'),
('IC10238-2','C10238','LENDING','2026-08-19 15:05:00','CALL','Fee dispute',TRUE,'OPEN',-0.7,'Disputes INR 11,800 processing fee on personal loan top-up he never availed. Reversal promised within 7 days.',TRUE,'PERSONA'),
('IC10238-3','C10238','LENDING','2026-09-03 10:40:00','CHAT','App outage',TRUE,'RESOLVED',-0.5,'Could not log in to app for 2 days; unsure if EMI auto-debit went through.',FALSE,'PERSONA'),
('IC10238-4','C10238','LENDING','2026-09-12 17:30:00','BRANCH','Agent behaviour complaint',TRUE,'ESCALATED',-0.8,'Complained branch executive was dismissive about the pending fee reversal.',FALSE,'PERSONA'),
('IC10238-5','C10238','LENDING','2026-09-28 12:10:00','CALL','Fee dispute',TRUE,'OPEN',-0.8,'Third follow-up on fee reversal. Mentions competitor balance-transfer offer at 8.25% and fixed-rate reset on 23-Oct.',TRUE,'PERSONA'),
-- C10417 Rohan Das
('IC10417-1','C10417','LENDING','2026-08-07 09:50:00','APP','Payment failed',FALSE,'RESOLVED',-0.2,'EMI auto-debit bounced (insufficient funds).',FALSE,'PERSONA'),
('IC10417-2','C10417','LENDING','2026-09-09 14:15:00','CALL','Payment difficulty',FALSE,'OPEN',-0.5,'Lost job in August; asked for EMI reduction or moratorium.',TRUE,'PERSONA'),
('IC10417-3','C10417','LENDING','2026-09-25 18:00:00','WHATSAPP','Late fee complaint',TRUE,'OPEN',-0.6,'Unhappy with repeated collection calls and late fees.',FALSE,'PERSONA'),
-- C10555 Kavya Iyer
('IC10555-1','C10555','LENDING','2026-07-15 13:00:00','APP','Top-up loan enquiry',FALSE,'RESOLVED',0.4,'Viewed pre-approved offers page.',FALSE,'PERSONA'),
('IC10555-2','C10555','LENDING','2026-09-21 16:45:00','CALL','Limit increase',FALSE,'RESOLVED',0.6,'Hitting card limit on travel spend; promoted; asked for premium travel card.',TRUE,'PERSONA'),
-- C10789 Karthik Nair
('IC10789-1','C10789','INSURANCE','2026-08-30 10:00:00','EMAIL','Coverage question',FALSE,'RESOLVED',0.1,'Asked whether newborn expenses are covered under individual health policy.',FALSE,'PERSONA'),
('IC10789-2','C10789','INSURANCE','2026-09-24 11:35:00','CALL','Add family member',FALSE,'OPEN',0.3,'Newborn daughter; wants wife and daughter covered; no life cover.',TRUE,'PERSONA'),
-- C10901 Lakshmi Rao
('IC10901-1','C10901','LENDING','2026-05-11 10:10:00','EMAIL','Interest rate query',FALSE,'RESOLVED',0.2,'Asked about auto loan rate; explained.',FALSE,'PERSONA'),
-- C11024 Priya Kulkarni
('IC11024-1','C11024','INSURANCE','2026-08-12 12:00:00','CALL','Claim delay',TRUE,'OPEN',-0.6,'Motor claim (rear-end collision) pending 7 weeks; surveyor report awaited.',TRUE,'PERSONA'),
('IC11024-2','C11024','INSURANCE','2026-09-26 19:20:00','CALL','Renewal premium query',FALSE,'OPEN',-0.4,'Renewal premium up 18%; asks for loyalty discount while claim still unsettled.',TRUE,'PERSONA');

INSERT INTO CALL_TRANSCRIPT (TRANSCRIPT_ID, INTERACTION_ID, CUSTOMER_ID, CALL_TS, DURATION_SEC, SOURCE_TYPE, SOURCE_FILE, TRANSCRIPT_TEXT)
VALUES
('TR-IC10238-2','IC10238-2','C10238','2026-08-19 15:05:00',412,'SYNTHETIC_TEXT','synthetic://transcripts/IC10238-2.txt',
'AGENT: Thank you for calling, this is Neha. How can I help you today?
CUSTOMER: Hi Neha. I see a processing fee of eleven thousand eight hundred rupees on my personal loan statement.
CUSTOMER: I never took any top-up. I did not sign anything for this.
AGENT: I can see the charge. It looks like it was applied in error. I will raise a reversal request.
CUSTOMER: How long will that take?
AGENT: It should be reversed within seven working days.
CUSTOMER: Fine. I have had my home loan with you for eight years, I expect this to be handled properly.
AGENT: Absolutely, sir. Your reference number is SR-48211.'),
('TR-IC10238-5','IC10238-5','C10238','2026-09-28 12:10:00',538,'SYNTHETIC_TEXT','synthetic://transcripts/IC10238-5.txt',
'AGENT: Thank you for calling, how may I help?
CUSTOMER: This is the third time I am calling about the same fee reversal. Reference SR-48211.
CUSTOMER: I was told seven days. It has been almost six weeks. Nobody has called me back.
AGENT: I am very sorry, sir. I can see the request is still pending with the operations team.
CUSTOMER: And when I went to the branch the executive just told me to check the app, which was down that week.
CUSTOMER: Honestly, another bank has offered me a balance transfer on my home loan at eight point two five percent.
CUSTOMER: My fixed rate ends on the twenty third of October. If this is how I am treated I will move everything, the home loan, the personal loan and the card.
AGENT: I understand your frustration. I will escalate this to a senior relationship manager today.
CUSTOMER: I want the fee reversed and someone senior to actually call me. Not another reference number.'),
('TR-IC10417-2','IC10417-2','C10417','2026-09-09 14:15:00',366,'SYNTHETIC_TEXT','synthetic://transcripts/IC10417-2.txt',
'AGENT: Hello Mr Das, this is a courtesy call about the EMI on your personal loan that is overdue.
CUSTOMER: Yes, I know. My company shut down its Hyderabad office in August and I lost my job.
CUSTOMER: I have always paid on time for almost two years. I do not want to become a defaulter.
AGENT: I understand. Are you able to make a partial payment this month?
CUSTOMER: Maybe a small amount. I have interviews lined up, I should have something in two or three months.
CUSTOMER: Is there a way to reduce the EMI or get a short break? The late fees are making it worse.
AGENT: I will note your request for a hardship review.
CUSTOMER: Please. I do not need any new offers or cards right now, I just need breathing room.'),
('TR-IC10555-2','IC10555-2','C10555','2026-09-21 16:45:00',295,'SYNTHETIC_TEXT','synthetic://transcripts/IC10555-2.txt',
'AGENT: Good afternoon, thank you for calling.
CUSTOMER: Hi, I travel a lot more for work now and I keep hitting the limit on my credit card.
CUSTOMER: I was promoted in July, so my salary has gone up as well.
CUSTOMER: Do you have a card with better travel rewards and lounge access? A friend has one from another bank.
AGENT: Based on your history you may qualify for our Voyager premium travel card.
CUSTOMER: That would be great. I would rather stay with you if the benefits are similar.
AGENT: I will note your interest and someone will share the details.'),
('TR-IC10789-2','IC10789-2','C10789','2026-09-24 11:35:00',447,'SYNTHETIC_TEXT','synthetic://transcripts/IC10789-2.txt',
'AGENT: Hello Mr Nair, how can I help you today?
CUSTOMER: We had a baby girl last month and I want to make sure she is covered.
CUSTOMER: Right now I only have an individual health policy. Can I add my wife and daughter to it?
AGENT: An individual policy cannot add members mid-term, but a family floater can cover all three of you.
CUSTOMER: Okay. Also, I realised I do not have any life insurance. With a child now I think I really need it.
AGENT: That is a very sensible thought. I can arrange an advisor to walk you through family floater and term options.
CUSTOMER: Yes please. I prefer a phone call, evenings are best.'),
('TR-IC11024-1','IC11024-1','C11024','2026-08-12 12:00:00',380,'SYNTHETIC_TEXT','synthetic://transcripts/IC11024-1.txt',
'AGENT: Thank you for calling.
CUSTOMER: I filed a claim for my car seven weeks ago after someone rear-ended me. It is still pending.
AGENT: I can see the surveyor report has not been uploaded yet.
CUSTOMER: I have sent the photos and the FIR copy twice. Nobody tells me what is happening.
AGENT: I apologise. I will chase the surveyor today.
CUSTOMER: Please do. I am paying for repairs out of pocket.'),
('TR-IC11024-2','IC11024-2','C11024','2026-09-26 19:20:00',322,'SYNTHETIC_TEXT','synthetic://transcripts/IC11024-2.txt',
'AGENT: Good evening, how can I help?
CUSTOMER: I got the renewal notice for my motor policy. The premium is eighteen percent higher.
CUSTOMER: My claim from August is still not settled and now you want more money?
CUSTOMER: I have been with you six years. Can you give me a loyalty discount?
AGENT: Let me check what options are available before your renewal on the thirtieth.
CUSTOMER: Honestly, I mostly want my claim closed. Then we can talk about renewal.');

INSERT INTO FACT_CLAIM_OR_LOAN_EVENT VALUES
('EC10238-FEE','C10238','AC10238-2','LENDING','FEE_DISPUTE','2026-08-19','OPEN',11800,'Processing fee charged in error; reversal SR-48211 pending since 19-Aug'),
('EC10238-FCL','C10238','AC10238-1','LENDING','FORECLOSURE_ENQUIRY','2026-09-29','OPEN',11200000,'Requested foreclosure statement for home loan (balance transfer)'),
('EC10417-RST','C10417','AC10417-1','LENDING','RESTRUCTURE_REQUEST','2026-09-09','OPEN',0,'Hardship review requested after job loss'),
('EC10555-TOP','C10555','AC10555-1','LENDING','TOPUP_ENQUIRY','2026-09-21','OPEN',0,'Interest in premium travel card / higher limit'),
('EC10789-END','C10789','AC10789-1','INSURANCE','ENDORSEMENT_REQUEST','2026-09-24','OPEN',0,'Wants to add spouse and newborn'),
('EC11024-CLM','C11024','AC11024-1','INSURANCE','CLAIM_DELAYED','2026-06-20','OPEN',86000,'Motor OD claim, surveyor report pending 14+ weeks'),
('EC11024-CL0','C11024','AC11024-1','INSURANCE','CLAIM_SETTLED','2026-01-14','CLOSED',24000,'Windshield claim settled');
