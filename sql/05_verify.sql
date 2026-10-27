SELECT * FROM auction.verify_invariants();
DO $$ DECLARE v_bad text; BEGIN
    SELECT string_agg(check_name,', ') INTO v_bad FROM auction.verify_invariants() WHERE NOT passed;
    IF v_bad IS NOT NULL THEN RAISE EXCEPTION 'Vi phạm bất biến: %',v_bad; END IF;
END $$;
