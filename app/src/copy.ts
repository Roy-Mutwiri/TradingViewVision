export const copy={
  app:{settings:'Settings',studio:'STUDIO'},
  chart:{scan:'ORACLE SCANNING FOR SIGNAL',marketClosed:'MARKET CLOSED',feedRetry:'FEED NOT READY - RETRYING 3s',preparing:'Preparing chart',loading:'Loading candles'},
  rail:{nextClose:'SESSION EVENT',nextSession:'REOPENS IN',liveSignal:'LIVE SIGNAL',scanning:'SCANNING',indicators:'INDICATORS',state:'STATE',since:'SINCE',keyLevels:'KEY LEVELS',deltaUsd:'Δ USD',structure:'STRUCTURE',utc:'UTC',worklog:'WORKLOG',scoreboard:'SCOREBOARD',lossesStay:'LOSSES STAY',last20:'LAST 20',today:'TODAY',allTime:'ALL TIME',comments:'LIVE COMMENTS',waiting:'WAITING'},
  signal:{noCall:'Waiting for discount',scanNear:'below',waitingFor:(gate:string,side:string,price:string)=>`Waiting for ${gate.toLowerCase()}  ${side} ${price}`,onlyZone:(kind:string,range:string,side:string,eq:string)=>`Only ${kind} ${range} sits ${side} EQ ${eq}`},
  joins:{none:'No new joins',joined:'joined',welcomeBack:'welcome back'},
  score:{produced:'PRODUCED',triggered:'TRIGGERED',resolved:'RESOLVED',win:'WIN',loss:'LOSS',scratch:'SCRATCH',never:'NEVER TRIG',cancelled:'CANCELLED',void:'VOID',hit:'HIT',expect:'EXPECT.'},
  footer:{disclaimer:'Educational market analysis / Not financial advice / ORACLE never trades'},
  trendPending:'Bias pending',
  commentsWaiting:'Waiting for comments',
  worklog:{decision:(action:string,tf:string,kind:string,detail:string)=>`${tf} ${kind.toUpperCase()} ${action}${detail?`  ${detail}`:''}`},
};