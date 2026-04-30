-- migration 008: YouTube Analytics metrics (canal próprio).
-- CTR / AVD / retention são privadas — só acessíveis via OAuth do dono do canal.
-- Aliments a aba "Performance própria" do dashboard e features de Fase 6.

CREATE TABLE IF NOT EXISTS youtube_analytics_metrics (
    video_id                  VARCHAR NOT NULL,
    date                      DATE NOT NULL,
    views                     BIGINT,
    impressions               BIGINT,
    impression_ctr            DOUBLE,    -- impressionClickThroughRate (0..100, %)
    avg_view_duration_seconds DOUBLE,    -- averageViewDuration
    avg_view_percentage       DOUBLE,    -- averageViewPercentage (0..100, %)
    fetched_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (video_id, date)
);

CREATE INDEX IF NOT EXISTS idx_yt_analytics_video ON youtube_analytics_metrics(video_id);
CREATE INDEX IF NOT EXISTS idx_yt_analytics_date  ON youtube_analytics_metrics(date);
