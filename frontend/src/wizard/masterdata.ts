// Mirrors lib/llm/masterdata.ts from the reference project so the wizard
// dropdowns match the Moonstride MasterData validation lists.

export const ALLOWED_MEAL_PLANS = [
  "All inclusive",
  "American",
  "As brochured",
  "Bed and Breakfast",
  "Breakfast",
  "Continental breakfast",
  "Dinner",
  "European",
  "Family plan",
  "Full board",
  "Full breakfast",
  "Half board",
  "Lunch",
  "Modified American",
  "No meals",
  "Room only",
  "Self-catering",
  "Ultra All Inclusive",
];

export const ALLOWED_BED_TYPES = [
  "Double",
  "Full",
  "Futon",
  "King",
  "Queen",
  "Single",
  "Sofa bed",
  "Twin",
  "Murphy bed",
  "Dorm bed",
  "Run of the house",
  "Tatami mats",
  "Water bed",
];

export const ALLOWED_STAR_RATINGS = [
  "1 Star",
  "2 Star",
  "3 Star",
  "4 Star",
  "5 Star",
  "6 Star",
  "7 Star",
  "Boutique Hotel",
  "Self Catering",
];

export const ALLOWED_STATUSES = ["Open", "On Request", "Close", "Company Close"];

export const COUNTRY_CODES = [
  "AF","AL","DZ","AS","AD","AO","AI","AQ","AG","AR","AM","AW","AU","AT","AZ",
  "BS","BH","BD","BB","BY","BE","BZ","BJ","BM","BT","BO","BA","BW","BV","BR",
  "IO","BN","BG","BF","BI","KH","CM","CA","CV","KY","CF","TD","CL","CN","CX",
  "CC","CO","KM","CG","CD","CK","CR","CI","HR","CU","CY","CZ","DK","DJ","DM",
  "DO","EC","EG","SV","GQ","ER","EE","ET","FK","FO","FJ","FI","FR","GF","PF",
  "TF","GA","GM","GE","DE","GH","GI","GR","GL","GD","GP","GU","GT","GN","GW",
  "GY","HT","HM","VA","HN","HK","HU","IS","IN","ID","IR","IQ","IE","IL","IT",
  "JM","JP","JO","KZ","KE","KI","KP","KR","KW","KG","LA","LV","LB","LS","LR",
  "LY","LI","LT","LU","MO","MK","MG","MW","MY","MV","ML","MT","MH","MQ","MR",
  "MU","YT","MX","FM","MD","MC","MN","MS","MA","MZ","MM","NA","NR","NP","NL",
  "AN","NC","NZ","NI","NE","NG","NU","NF","MP","NO","OM","PK","PW","PS","PA",
  "PG","PY","PE","PH","PN","PL","PT","PR","QA","RE","RO","RU","RW","SH","KN",
  "LC","PM","VC","WS","SM","ST","SA","SN","CS","SC","SL","SG","SK","SI","SB",
  "SO","ZA","GS","ES","LK","SD","SR","SJ","SZ","SE","CH","SY","TW","TJ","TZ",
  "TH","TL","TG","TK","TO","TT","TN","TR","TM","TC","TV","UG","UA","AE","GB",
  "US","UM","UY","UZ","VU","VE","VN","VG","VI","WF","EH","YE","ZM","ZW",
];

export const RATE_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "moonstride_ppn", label: "Per Person Per Night" },
  { value: "moonstride_prn_ac", label: "Per Room Per Night (Adult / Child count)" },
  { value: "moonstride_prn_pax", label: "Per Room Per Night (Pax count)" },
];
