# app/db_triggers.py
# PostgreSQL triggers for reviews schema — run on app startup.
# Tables are created by Base.metadata.create_all(); triggers need raw SQL.

from sqlalchemy import text
from app.database import engine


def install_review_triggers():
    """Create triggers that update heritage_sites.rating and analyzed_responses."""
    with engine.connect() as conn:
        # Trigger: update heritage_sites.rating when site_ratings changes
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_site_rating_from_ratings()
            RETURNS TRIGGER AS $$
            BEGIN
                UPDATE heritage_sites
                SET rating = (
                    SELECT COALESCE(AVG(rating)::float, 0)
                    FROM site_ratings
                    WHERE site_id = COALESCE(NEW.site_id, OLD.site_id)
                )
                WHERE id = COALESCE(NEW.site_id, OLD.site_id);
                RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(text("DROP TRIGGER IF EXISTS trg_site_ratings_update_heritage_rating ON site_ratings"))
        conn.execute(text("""
            CREATE TRIGGER trg_site_ratings_update_heritage_rating
                AFTER INSERT OR UPDATE OR DELETE ON site_ratings
                FOR EACH ROW EXECUTE FUNCTION update_site_rating_from_ratings();
        """))
        conn.commit()

        # Trigger: update analyzed_responses when trip_reviews changes
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_analyzed_from_trip_reviews()
            RETURNS TRIGGER AS $$
            DECLARE
                v_site_id INTEGER;
                v_avg_star FLOAT;
                v_total_ratings INT;
                v_avg_q1 FLOAT;
                v_avg_q2 FLOAT;
                v_avg_q3 FLOAT;
                v_total_reviews INT;
                v_recommend_pct FLOAT;
                v_label VARCHAR;
            BEGIN
                v_site_id := COALESCE(NEW.site_id, OLD.site_id);
                SELECT COALESCE(AVG(rating), 0), COUNT(*) INTO v_avg_star, v_total_ratings
                FROM site_ratings WHERE site_id = v_site_id;
                SELECT
                    COALESCE(AVG(q1_overall_experience), 0),
                    COALESCE(AVG(q2_guide_helpfulness), 0),
                    COALESCE(AVG(q3_recommend_to_others), 0),
                    COUNT(*),
                    CASE WHEN COUNT(*) > 0 THEN 100.0 * COUNT(*) FILTER (WHERE q3_recommend_to_others >= 4) / NULLIF(COUNT(*), 0) ELSE 0 END
                INTO v_avg_q1, v_avg_q2, v_avg_q3, v_total_reviews, v_recommend_pct
                FROM trip_reviews WHERE site_id = v_site_id;
                v_label := CASE
                    WHEN v_total_reviews = 0 THEN 'No data'
                    WHEN v_avg_q1 >= 4.5 THEN 'Excellent'
                    WHEN v_avg_q1 >= 4.0 THEN 'Good'
                    WHEN v_avg_q1 >= 3.0 THEN 'Average'
                    ELSE 'Poor'
                END;
                INSERT INTO analyzed_responses (site_id, avg_star_rating, total_ratings, avg_overall_experience,
                    avg_guide_helpfulness, avg_recommend_score, total_reviews, recommend_pct, satisfaction_label, last_updated)
                VALUES (v_site_id, v_avg_star, v_total_ratings, v_avg_q1, v_avg_q2, v_avg_q3, v_total_reviews, v_recommend_pct, v_label, now())
                ON CONFLICT (site_id) DO UPDATE SET
                    avg_star_rating = EXCLUDED.avg_star_rating, total_ratings = EXCLUDED.total_ratings,
                    avg_overall_experience = EXCLUDED.avg_overall_experience,
                    avg_guide_helpfulness = EXCLUDED.avg_guide_helpfulness,
                    avg_recommend_score = EXCLUDED.avg_recommend_score,
                    total_reviews = EXCLUDED.total_reviews, recommend_pct = EXCLUDED.recommend_pct,
                    satisfaction_label = EXCLUDED.satisfaction_label, last_updated = now();
                RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(text("DROP TRIGGER IF EXISTS trg_trip_reviews_update_analyzed ON trip_reviews"))
        conn.execute(text("""
            CREATE TRIGGER trg_trip_reviews_update_analyzed
                AFTER INSERT OR UPDATE OR DELETE ON trip_reviews
                FOR EACH ROW EXECUTE FUNCTION update_analyzed_from_trip_reviews();
        """))
        conn.commit()

        # Trigger: update analyzed_responses when site_ratings changes (star rating only)
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_analyzed_from_site_ratings()
            RETURNS TRIGGER AS $$
            DECLARE
                v_site_id INTEGER;
                v_avg_star FLOAT;
                v_total_ratings INT;
            BEGIN
                v_site_id := COALESCE(NEW.site_id, OLD.site_id);
                SELECT COALESCE(AVG(rating), 0), COUNT(*) INTO v_avg_star, v_total_ratings
                FROM site_ratings WHERE site_id = v_site_id;
                INSERT INTO analyzed_responses (site_id, avg_star_rating, total_ratings, last_updated)
                VALUES (v_site_id, v_avg_star, v_total_ratings, now())
                ON CONFLICT (site_id) DO UPDATE SET
                    avg_star_rating = EXCLUDED.avg_star_rating,
                    total_ratings = EXCLUDED.total_ratings,
                    last_updated = now();
                RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(text("DROP TRIGGER IF EXISTS trg_site_ratings_update_analyzed ON site_ratings"))
        conn.execute(text("""
            CREATE TRIGGER trg_site_ratings_update_analyzed
                AFTER INSERT OR UPDATE OR DELETE ON site_ratings
                FOR EACH ROW EXECUTE FUNCTION update_analyzed_from_site_ratings();
        """))
        conn.commit()

